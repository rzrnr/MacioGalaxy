# Guglis Edits (guglis/README.md): the app gets the Super Mario Galaxy icon.
# actool compiles the Icon Composer package into Assets.car (the Liquid Glass icon, found through
# CFBundleIconName) and an .icns for older macOS. Without xcrun the app is built without an icon.
find_program(GUGLIS_XCRUN xcrun)
if(NOT GUGLIS_XCRUN)
    message(WARNING "Guglis Edits: xcrun not found, building the app without the Super Mario Galaxy icon")
    return()
endif()

set(_guglis_icon "${CMAKE_CURRENT_LIST_DIR}/SuperMarioGalaxy.icon")
set(_guglis_icon_out "${CMAKE_CURRENT_BINARY_DIR}/guglis-icon")
set(_guglis_icon_files "${_guglis_icon_out}/Assets.car" "${_guglis_icon_out}/SuperMarioGalaxy.icns")
file(GLOB_RECURSE _guglis_icon_inputs CONFIGURE_DEPENDS "${_guglis_icon}/*")
add_custom_command(
    OUTPUT ${_guglis_icon_files}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${_guglis_icon_out}"
    COMMAND "${GUGLIS_XCRUN}" actool "${_guglis_icon}" --compile "${_guglis_icon_out}" --platform macosx
            --minimum-deployment-target 14.0 --target-device mac --app-icon SuperMarioGalaxy
            --output-partial-info-plist "${_guglis_icon_out}/partial.plist" --output-format human-readable-text
    DEPENDS ${_guglis_icon_inputs}
    COMMENT "Guglis Edits: compiling the Super Mario Galaxy app icon"
    VERBATIM)
target_sources(petari PRIVATE ${_guglis_icon_files})
set_source_files_properties(${_guglis_icon_files} PROPERTIES GENERATED TRUE MACOSX_PACKAGE_LOCATION Resources)
# CMake's default bundle Info.plist plus CFBundleIconName.
set_target_properties(petari PROPERTIES
    MACOSX_BUNDLE_ICON_FILE SuperMarioGalaxy
    MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_LIST_DIR}/Info.plist.in")
