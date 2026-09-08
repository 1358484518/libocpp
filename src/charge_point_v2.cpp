// SPDX-License-Identifier: Apache-2.0
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <thread>

#include <boost/program_options.hpp>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <everest/logging.hpp>
#include <nlohmann/json.hpp>

#include <ocpp/common/evse_security_impl.hpp>
#include <ocpp/common/support_older_cpp_versions.hpp>
#include <ocpp/v2/charge_point.hpp>
#include <ocpp/v2/ocpp_enums.hpp>
#include <ocpp/v2/types.hpp>

namespace po = boost::program_options;

static ocpp::v2::MeterValue make_meter(float wh) {
    ocpp::v2::MeterValue mv;
    mv.timestamp = ocpp::DateTime();
    ocpp::v2::SampledValue sv;
    sv.value = wh;
    sv.measurand = ocpp::v2::MeasurandEnum::Energy_Active_Import_Register;
    mv.sampledValue = {sv};
    return mv;
}

static ocpp::v2::IdToken make_token(const std::string& id) {
    ocpp::v2::IdToken token;
    token.idToken = id;
    token.type = ocpp::v2::IdTokenEnumStringType::ISO14443;
    return token;
}

static ocpp::v2::Callbacks make_callbacks(ocpp::v2::ChargePoint*& cp, std::string& session_id,
                                          std::shared_ptr<std::atomic<bool>> boot_ok,
                                          std::shared_ptr<std::mutex> boot_m,
                                          std::shared_ptr<std::condition_variable> boot_cv) {
    ocpp::v2::Callbacks cb;
    cb.is_reset_allowed_callback = [](const std::optional<const std::int32_t>&, const ocpp::v2::ResetEnum&) {
        return true;
    };
    cb.reset_callback = [](const std::optional<const std::int32_t>&, const ocpp::v2::ResetEnum& t) {
        std::cout << "Callback: Reset " << ocpp::v2::conversions::reset_enum_to_string(t) << std::endl;
    };
    cb.stop_transaction_callback = [&](const std::int32_t evse_id, const ocpp::v2::ReasonEnum reason) {
        std::cout << "Callback: CSMS stop transaction evse=" << evse_id << std::endl;
        if (cp != nullptr && !session_id.empty()) {
            cp->on_transaction_finished(evse_id, ocpp::DateTime(), make_meter(2500.f), reason,
                                        ocpp::v2::TriggerReasonEnum::RemoteStop, make_token("DEADBEEF"), std::nullopt,
                                        ocpp::v2::ChargingStateEnum::Idle);
            cp->on_session_finished(evse_id, 1);
            session_id.clear();
        }
        return ocpp::v2::RequestStartStopStatusEnum::Accepted;
    };
    cb.pause_charging_callback = [](std::int32_t) {};
    cb.connector_effective_operative_status_changed_callback =
        [](std::int32_t, std::int32_t, ocpp::v2::OperationalStatusEnum) {};
    cb.get_log_request_callback = [](const ocpp::v2::GetLogRequest&) {
        ocpp::v2::GetLogResponse r;
        r.status = ocpp::v2::LogStatusEnum::Rejected;
        return r;
    };
    cb.unlock_connector_callback = [](std::int32_t, std::int32_t) {
        ocpp::v2::UnlockConnectorResponse r;
        r.status = ocpp::v2::UnlockStatusEnum::Unlocked;
        return r;
    };
    cb.remote_start_transaction_callback = [&](const ocpp::v2::RequestStartTransactionRequest& req, bool) {
        std::cout << "Callback: RequestStartTransaction" << std::endl;
        if (cp == nullptr) {
            return ocpp::v2::RequestStartStopStatusEnum::Rejected;
        }
        const auto evse = req.evseId.value_or(1);
        session_id = boost::uuids::to_string(boost::uuids::random_generator()());
        cp->on_session_started(evse, 1);
        auto token = req.idToken;
        cp->on_transaction_started(evse, 1, session_id, ocpp::DateTime(), ocpp::v2::TriggerReasonEnum::RemoteStart,
                                   make_meter(0.f), token, std::nullopt, std::nullopt, req.remoteStartId,
                                   ocpp::v2::ChargingStateEnum::Charging);
        return ocpp::v2::RequestStartStopStatusEnum::Accepted;
    };
    cb.is_reservation_for_token_callback = [](std::int32_t, ocpp::CiString<255>, std::optional<ocpp::CiString<255>>) {
        return ocpp::ReservationCheckStatus::NotReserved;
    };
    cb.update_firmware_request_callback = [](const ocpp::v2::UpdateFirmwareRequest&) {
        ocpp::v2::UpdateFirmwareResponse r;
        r.status = ocpp::v2::UpdateFirmwareStatusEnum::Rejected;
        return r;
    };
    cb.security_event_callback = [](const ocpp::CiString<50>&, const std::optional<ocpp::CiString<255>>&) {};
    cb.set_charging_profiles_callback = []() {};
    cb.reserve_now_callback = [](const ocpp::v2::ReserveNowRequest&) {
        return ocpp::v2::ReserveNowStatusEnum::Rejected;
    };
    cb.cancel_reservation_callback = [](const std::int32_t) { return false; };
    cb.boot_notification_callback = [boot_ok, boot_m, boot_cv](const ocpp::v2::BootNotificationResponse& boot) {
        std::cout << "BootNotification.conf status="
                  << ocpp::v2::conversions::registration_status_enum_to_string(boot.status) << std::endl;
        if (boot.status == ocpp::v2::RegistrationStatusEnum::Accepted) {
            std::lock_guard<std::mutex> lk(*boot_m);
            *boot_ok = true;
            boot_cv->notify_all();
        }
    };
    return cb;
}

int main(int argc, char* argv[]) {
    po::options_description desc("OCPP 2.0.1 charge point (libocpp)");
    desc.add_options()("help,h", "help");
    desc.add_options()("config-dir", po::value<std::string>(), "component_config directory");
    desc.add_options()("migrations", po::value<std::string>(), "device_model_migrations directory");
    desc.add_options()("core-migrations", po::value<std::string>(), "core_migrations directory");
    desc.add_options()("logconf", po::value<std::string>(), "logging.ini");
    desc.add_options()("auto-session", "after Boot Accepted, start/stop DEADBEEF transaction and exit");
    desc.add_options()("db-dir", po::value<std::string>(), "directory for device_model.db and cp.db");

    po::variables_map vm;
    po::store(po::parse_command_line(argc, argv, desc), vm);
    po::notify(vm);
    if (vm.count("help") != 0) {
        std::cout << desc << "\n";
        return 1;
    }

#ifdef OCPP201_CONFIG_DIR
    std::string config_dir = OCPP201_CONFIG_DIR;
#else
    std::string config_dir;
#endif
#ifdef OCPP201_MIGRATIONS
    std::string migrations = OCPP201_MIGRATIONS;
#else
    std::string migrations;
#endif
#ifdef OCPP201_CORE_MIGRATIONS
    std::string core_migrations = OCPP201_CORE_MIGRATIONS;
#else
    std::string core_migrations;
#endif
#ifdef OCPP_LOGGING_INI
    std::string logconf = OCPP_LOGGING_INI;
#else
    std::string logconf;
#endif
    if (vm.count("config-dir") != 0) {
        config_dir = vm["config-dir"].as<std::string>();
    }
    if (vm.count("migrations") != 0) {
        migrations = vm["migrations"].as<std::string>();
    }
    if (vm.count("core-migrations") != 0) {
        core_migrations = vm["core-migrations"].as<std::string>();
    }
    if (vm.count("logconf") != 0) {
        logconf = vm["logconf"].as<std::string>();
    }
    if (config_dir.empty() || migrations.empty() || core_migrations.empty()) {
        std::cerr << "Need --config-dir, --migrations, --core-migrations (or compile-time defaults)\n";
        return 1;
    }
    if (!logconf.empty()) {
        Everest::Logging::init(logconf, "charge_point_v2");
    }

    std::string db_dir = "/tmp/ocpp201-example";
    if (vm.count("db-dir") != 0) {
        db_dir = vm["db-dir"].as<std::string>();
    }
    fs::create_directories(db_dir);
    fs::create_directories("/tmp/certs/ca/v2g");
    fs::create_directories("/tmp/certs/ca/mo");
    fs::create_directories("/tmp/client/csms");
    fs::create_directories("/tmp/client/cso");
    if (!fs::is_regular_file("/tmp/certs/ca/v2g/V2G_CA_BUNDLE.pem")) {
        std::ofstream("/tmp/certs/ca/v2g/V2G_CA_BUNDLE.pem");
    }
    if (!fs::is_regular_file("/tmp/certs/ca/mo/MO_CA_BUNDLE.pem")) {
        std::ofstream("/tmp/certs/ca/mo/MO_CA_BUNDLE.pem");
    }

    ocpp::SecurityConfiguration sec;
    sec.csms_ca_bundle = "/tmp/certs/ca/v2g/V2G_CA_BUNDLE.pem";
    sec.mf_ca_bundle = sec.csms_ca_bundle;
    sec.v2g_ca_bundle = sec.csms_ca_bundle;
    sec.mo_ca_bundle = "/tmp/certs/ca/mo/MO_CA_BUNDLE.pem";
    sec.csms_leaf_cert_directory = "/tmp/client/csms/";
    sec.csms_leaf_key_directory = "/tmp/client/csms/";
    sec.secc_leaf_cert_directory = "/tmp/client/cso/";
    sec.secc_leaf_key_directory = "/tmp/client/cso/";
    auto evse_security = std::make_shared<ocpp::EvseSecurityImpl>(sec);

    ocpp::v2::ChargePoint* charge_point = nullptr;
    std::string session_id;
    auto boot_ok = std::make_shared<std::atomic<bool>>(false);
    auto boot_m = std::make_shared<std::mutex>();
    auto boot_cv = std::make_shared<std::condition_variable>();
    auto callbacks = make_callbacks(charge_point, session_id, boot_ok, boot_m, boot_cv);

    // Must match config/v2/component_config/custom (EVSE_1, EVSE_2, Connector_1_1, Connector_2_1).
    std::map<std::int32_t, std::int32_t> evse_map{{1, 1}, {2, 1}};
    std::error_code ec;
    fs::remove_all(db_dir + "/device_model.db", ec);
    fs::remove_all(db_dir + "/cp.db", ec);

    charge_point = new ocpp::v2::ChargePoint(evse_map, db_dir + "/device_model.db", migrations, config_dir, db_dir,
                                             db_dir, core_migrations, "/tmp", evse_security, callbacks);

    charge_point->start();

    auto run_session = [&]() {
        session_id = boost::uuids::to_string(boost::uuids::random_generator()());
        charge_point->on_session_started(1, 1);
        auto token = make_token("DEADBEEF");
        auto auth = charge_point->validate_token(token, std::nullopt, std::nullopt);
        if (auth.idTokenInfo.status != ocpp::v2::AuthorizationStatusEnum::Accepted) {
            std::cerr << "Authorize rejected\n";
            return false;
        }
        charge_point->on_transaction_started(1, 1, session_id, ocpp::DateTime(),
                                             ocpp::v2::TriggerReasonEnum::Authorized, make_meter(0.f), token,
                                             std::nullopt, std::nullopt, std::nullopt,
                                             ocpp::v2::ChargingStateEnum::Charging);
        std::this_thread::sleep_for(std::chrono::milliseconds(400));
        charge_point->on_meter_value(1, make_meter(1200.f));
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        charge_point->on_transaction_finished(1, ocpp::DateTime(), make_meter(2500.f), ocpp::v2::ReasonEnum::Local,
                                              ocpp::v2::TriggerReasonEnum::StopAuthorized, token, std::nullopt,
                                              ocpp::v2::ChargingStateEnum::Idle);
        charge_point->on_session_finished(1, 1);
        session_id.clear();
        std::this_thread::sleep_for(std::chrono::milliseconds(400));
        return true;
    };

    if (vm.count("auto-session") != 0) {
        std::unique_lock<std::mutex> lk(*boot_m);
        if (!boot_cv->wait_for(lk, std::chrono::seconds(25), [&] { return boot_ok->load(); })) {
            std::cerr << "Timed out waiting for BootNotification Accepted (start Python CSMS on port 9000)\n";
            charge_point->stop();
            delete charge_point;
            return 1;
        }
        lk.unlock();
        const bool ok = run_session();
        charge_point->stop();
        delete charge_point;
        return ok ? 0 : 2;
    }

    std::cout << "commands: start_transaction | stop_transaction | end\n";
    bool running = true;
    bool tx = false;
    while (running && !std::cin.fail()) {
        std::string cmd;
        std::cin >> cmd;
        if (cmd == "start_transaction" && !tx) {
            tx = run_session();
            tx = true;
        } else if (cmd == "stop_transaction") {
            tx = false;
        } else if (cmd == "end") {
            running = false;
        }
    }
    charge_point->stop();
    delete charge_point;
    return 0;
}
