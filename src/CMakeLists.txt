add_executable(charge_point charge_point.cpp)
add_executable(charge_point_v2 charge_point_v2.cpp)

foreach(_cp_target charge_point charge_point_v2)
    target_link_libraries(${_cp_target}
        PRIVATE
            Boost::thread
            Boost::program_options
            nlohmann_json::nlohmann_json
            nlohmann_json_schema_validator
            ocpp
            OpenSSL::SSL
            OpenSSL::Crypto
            SQLite::SQLite3
    )
    install(TARGETS ${_cp_target} RUNTIME)
endforeach()

target_compile_definitions(charge_point_v2 PRIVATE
    OCPP201_CONFIG_DIR="${CMAKE_SOURCE_DIR}/config/v2/component_config"
    OCPP201_MIGRATIONS="${CMAKE_SOURCE_DIR}/config/v2/device_model_migrations"
    OCPP201_CORE_MIGRATIONS="${CMAKE_SOURCE_DIR}/config/v2/core_migrations"
    OCPP_LOGGING_INI="${CMAKE_SOURCE_DIR}/config/logging.ini"
)

set_property(TARGET ocpp PROPERTY POSITION_INDEPENDENT_CODE ON)
