"""
Test module for timer management.
"""

import os
import logging
import time
from autotest.client import utils
from autotest.client.shared import error
from virttest.libvirt_xml import vm_xml, xcepts
from virttest import utils_test, virsh, data_dir, virt_vm


def set_xml_clock(vms, params):
    """
    Config libvirt XML for clock.
    """
    # Get a dict include operations to timer
    timer_elems = []
    if ("yes" == params.get("xml_timer", "no")) is True:
        timers = params.get("timers_attr", "").split('|')
        if len(timers):
            for timer in timers:
                timer_attrs = {}
                attrs = timer.split(';')
                for attr in attrs:
                    pairs = attr.split('=')
                    if len(pairs) != 2:
                        logging.error("timer attribute pairs '%s' do not"
                                      " match!SKIP...", pairs)
                        continue
                    key = pairs[0]
                    value = pairs[1]
                    timer_attrs[key] = value
                timer_elems.append(timer_attrs)
        else:
            logging.warn("xml_timer set to 'yes' but no timers provided!")

    offset = params.get("clock_offset", "utc")
    adjustment = params.get("clock_adjustment")
    timezone = params.get("clock_timezone")
    for vm in vms:
        vmclockxml = vm_xml.VMClockXML()
        vmclockxml.from_dumpxml(vm.name)
        vmclockxml.offset = offset
        del vmclockxml.adjustment
        del vmclockxml.timezone
        if adjustment is not None:
            vmclockxml.adjustment = adjustment
        if timezone is not None:
            vmclockxml.timezone = timezone
        # Clear timers for re-creating
        vmclockxml.timers = []
        newtimers = []
        for element in timer_elems:
            newtimer = vm_xml.VMClockXML.Timer()
            newtimer.update(element)
            newtimers.append(newtimer)
        vmclockxml.timers = newtimers
        logging.debug("New vm config:\n%s", vmclockxml)
        vmclockxml.sync()


def get_avail_clksrc(vm):
    """Get available clocksources in vm"""
    session = vm.wait_for_login()
    cd_cmd = "cd /sys/devices/system/clocksource/clocksource0/"
    get_cmd = "cat available_clocksource"
    # Get into path first
    session.cmd(cd_cmd)
    # Get available sources
    gets, geto = session.cmd_status_output(get_cmd)
    if gets:
        logging.debug("Get available clocksources failed:\n%s", geto)
        return []
    else:
        return geto.strip().split()


def get_current_clksrc(vm):
    """Get current clocksource in vm"""
    session = vm.wait_for_login()
    cd_cmd = "cd /sys/devices/system/clocksource/clocksource0/"
    get_cmd = "cat current_clocksource"
    # Get into path first
    session.cmd(cd_cmd)
    # Get current source
    gets, geto = session.cmd_status_output(get_cmd)
    if gets:
        logging.debug("Get current clocksource failed:\n%s", geto)
        return None
    else:
        return geto.strip()


def set_current_clksrc(vm, clocksource):
    """Set current clocksource in vm"""
    session = vm.wait_for_login()
    cd_cmd = "cd /sys/devices/system/clocksource/clocksource0/"
    set_cmd = "echo %s > current_clocksource" % clocksource
    # Get into path first
    session.cmd(cd_cmd)
    # Set current source
    sets, seto = session.cmd_status_output(set_cmd)
    if sets:
        logging.debug("Set current clocksource failed:\n%s", seto)
        return False
    return True


def recover_vm_xml(vms):
    """Recover to utc clock"""
    for vm in vms:
        logging.debug("Recover xml for %s", vm.name)
        vmclockxml = vm_xml.VMClockXML()
        vmclockxml.from_dumpxml(vm.name)
        del vmclockxml.adjustment
        del vmclockxml.timezone
        vmclockxml.offset = "utc"
        vmclockxml.timers = []
        try:
            vmclockxml.sync()
        except xcepts.LibvirtXMLError, detail:
            logging.error(detail)


def get_vm_time(vm, time_type=None, windows=False):
    """
    Return epoch time. Windows will return timezone only.

    :param time_type: UTC or timezone time
    """
    if time_type == "utc":
        cmd = "date -u +%s"
    elif windows is True:
        time_type == "tz"
        cmd = (r"echo %date:~0,4%/%date:~5,2%/%date:~8,2%/"
               "%time:~0,2%/%time:~3,2%/%time:~6,2%")
    else:
        cmd = "date +%Y/%m/%d/%H/%M/%S"
    session = vm.wait_for_login()
    ts, timestr = session.cmd_status_output(cmd)
    session.close()
    if ts:
        logging.error("Get time in vm failed:%s", timestr)
        return -1
    # To avoid some unexpected space, strip it manually
    if time_type == "utc":
        return int(timestr)
    else:
        # Strip potential space in timestr(for windows)
        elems = timestr.split('/')
        timestr = "%s/%s/%s/%s/%s/%s" % (elems[0].strip(), elems[1].strip(),
                                         elems[2].strip(), elems[3].strip(),
                                         elems[4].strip(), elems[5].strip())
        return int(time.mktime(time.strptime(timestr.strip(),
                                             '%Y/%m/%d/%H/%M/%S')))


def set_host_timezone(timezone="America/New_York"):
    """Set host timezone to what we want"""
    timezone_file = "/usr/share/zoneinfo/%s" % timezone
    if utils.run("ls %s" % timezone_file, ignore_status=True).exit_status:
        raise error.TestError("Not correct timezone:%s", timezone_file)
    else:
        utils.run("unlink /etc/localtime", ignore_status=True)
        result = utils.run("ln -s %s /etc/localtime" % timezone_file,
                           ignore_status=True)
        if result.exit_status:
            raise error.TestError("Set timezone failed:%s", result)


def set_vm_timezone(vm, timezone="America/New_York"):
    """Set vm timezone to what we want"""
    timezone_file = "/usr/share/zoneinfo/%s" % timezone
    session = vm.wait_for_login()
    if session.cmd_status("ls %s" % timezone_file):
        session.close()
        raise error.TestError("Not correct timezone:%s", timezone_file)
    else:
        session.cmd("unlink /etc/localtime")
        ts, to = session.cmd_status_output("ln -s %s /etc/localtime"
                                           % timezone_file)
        if ts:
            session.close()
            raise error.TestError("Set timezone failed:%s", to)
    session.close()


def set_windows_timezone(vm, timezone="America/New_York"):
    """Set windows vm timezone to what we want"""
    timezone_codes = {"America/New_York": "Eastern Standard Time",
                      "Europe/London": "UTC",
                      "Asia/Shanghai": "China Standard Time",
                      "Asia/Tokyo": "Tokyo Standard Time"}
    if timezone not in timezone_codes.keys():
        raise error.TestError("Not supported timezone, please add it.")
    cmd = "tzutil /s \"%s\"" % timezone_codes[timezone]
    session = vm.wait_for_login()
    ts, to = session.cmd_status_output(cmd)
    session.close()
    if ts:
        raise error.TestError("Set timezone failed:%s", to)


def convert_tz_to_vector(tz_name="Europe/London"):
    """
    Convert string of city to a vector with utc time(hours).
    """
    # TODO: inspect timezone automatically
    zoneinfo = {'0': ["Europe/London"],
                '8': ["Asia/HongKong", "Asia/Shanghai"],
                '9': ["Asia/Tokyo"],
                '-4': ["America/New_York"]}
    for key in zoneinfo:
        if tz_name in zoneinfo[key]:
            return int(key)
    logging.error("Not supported timezone:%s", tz_name)
    return None


def load_stress(vms, stress_type, params={}):
    """
    Load different stress in vm: unixbench, stress, running vms and so on
    """
    fail_info = []
    # Special operations for test
    if stress_type in ["stress_in_vms", "stress_on_host"]:
        logging.debug("Run stress %s", stress_type)
        fail_info = utils_test.load_stress(stress_type, vms, params)
    elif stress_type == "inject_nmi":
        inject_times = int(params.get("inject_times", 10))
        for vm in vms:
            while inject_times > 0:
                try:
                    inject_times -= 1
                    virsh.inject_nmi(vm.name, debug=True, ignore_status=False)
                except error.CmdError, detail:
                    fail_info.append("Inject operations failed:%s", detail)
    elif stress_type == "dump":
        dump_times = int(params.get("dump_times", 10))
        for vm in vms:
            while dump_times > 0:
                dump_times -= 1
                dump_path = os.path.join(data_dir.get_tmp_dir(), "dump.file")
                try:
                    virsh.dump(vm.name, dump_path, debug=True,
                               ignore_status=False)
                except (error.CmdError, OSError), detail:
                    fail_info.append("Create dump file for %s failed."
                                     % vm.name)
                try:
                    os.remove(dump_path)
                except OSError:
                    pass
    elif stress_type == "suspend_resume":
        paused_times = int(params.get("paused_times", 10))
        for vm in vms:
            while paused_times > 0:
                paused_times -= 1
                try:
                    virsh.suspend(vm.name, debug=True, ignore_status=False)
                    virsh.resume(vm.name, debug=True, ignore_status=False)
                except error.CmdError, detail:
                    fail_info.append("Suspend-Resume %s failed." % vm.name)
    elif stress_type == "save_restore":
        save_times = int(params.get("save_times", 10))
        for vm in vms:
            while save_times > 0:
                save_times -= 1
                save_path = os.path.join(data_dir.get_tmp_dir(), "save.file")
                try:
                    virsh.save(vm.name, save_path, debug=True,
                               ignore_status=False)
                    virsh.restore(save_path, debug=True,
                                  ignore_status=False)
                except error.CmdError:
                    fail_info.append("Save-Restore %s failed." % vm.name)
                try:
                    os.remove(save_path)
                except OSError:
                    pass
    return fail_info


def unload_stress(stress_type, params):
    """Cleanup stress on host"""
    if stress_type == "stress_on_host":
        utils_test.HostStress(params, "stress").unload_stress()


def test_all_timers(vms, params):
    """
    Test all available timers in vm.
    """
    host_tz = params.get("host_timezone", "Asia/Tokyo")
    vm_tz = params.get("vm_timezone", "America/New_York")
    clock_tz = params.get("clock_timezone", "Asia/Shanghai")
    host_tz_vector = convert_tz_to_vector(host_tz)
    vm_tz_vector = convert_tz_to_vector(vm_tz)
    set_tz_vector = convert_tz_to_vector(clock_tz)
    if ((host_tz_vector is None) or (vm_tz_vector is None)
            or (set_tz_vector is None)):
        raise error.TestError("Not supported timezone to convert.")
    delta = int(params.get("allowd_delta", "300"))

    # Confirm vm is down for editing
    for vm in vms:
        if vm.is_alive():
            vm.destroy()

    # Config clock in VMXML
    set_xml_clock(vms, params)

    # Logging vm to set time
    for vm in vms:
        vm.start()
        vm.wait_for_login()
        set_vm_timezone(vm, params.get("vm_timezone"))

    # Set host timezone
    set_host_timezone(params.get("host_timezone"))

    # Load stress if necessary
    stress_type = params.get("stress_type")
    if stress_type is not None:
        load_stress(vms, stress_type, params)

    # Get expected utc distance between host and vms
    # with different offset(seconds)
    offset = params.get("clock_offset", "utc")
    # No matter what utc is, the timezone distance
    vm_tz_span = vm_tz_vector * 3600
    host_tz_span = host_tz_vector * 3600
    if offset == "utc":
        utc_span = 0
    elif offset == "localtime":
        utc_span = host_tz_vector * 3600
    elif offset == "timezone":
        utc_span = set_tz_vector * 3600
    elif offset == "variable":
        utc_span = int(params.get("clock_adjustment", 3600))

    # TODO: It seems that actual timezone time in vm is only based on
    # timezone on host. I need to confirm whether it is normal(or bug)
    vm_tz_span = vm_tz_span - host_tz_span

    # To track failed information
    fail_info = []

    # Set vms' clocksource(different vm may have different sources)
    # (kvm-clock tsc hpet acpi_pm...)
    for vm in vms:
        # Get available clocksources
        avail_srcs = get_avail_clksrc(vm)
        if not avail_srcs:
            fail_info.append("Get available clocksources of %s "
                             "failed." % vm.name)
            continue
        logging.debug("Available clocksources of %s:%s", vm.name, avail_srcs)

        for clocksource in avail_srcs:
            if not set_current_clksrc(vm, clocksource):
                fail_info.append("Set clocksource to %s in %s failed."
                                 % (clocksource, vm.name))
                continue

            # Wait 2s to let new clocksource stable
            time.sleep(2)

            newclksrc = get_current_clksrc(vm)
            logging.debug("\nExpected clocksource:%s\n"
                          "Actual clocksource:%s", clocksource, newclksrc)
            if newclksrc.strip() != clocksource.strip():
                fail_info.append("Set clocksource passed, but current "
                                 "clocksource is not set one.")
                continue

            # Get vm's utc time and timezone time
            vm_utc_tm = get_vm_time(vm, "utc")
            vm_tz_tm = get_vm_time(vm, "tz")
            # Get host's utc time and timezone time
            host_utc_tm = int(time.time())

            logging.debug("\nUTC time in vm:%s\n"
                          "TimeZone time in vm:%s\n"
                          "UTC time on host:%s\n",
                          vm_utc_tm, vm_tz_tm, host_utc_tm)

            # Check got time
            # Distance between vm and host
            utc_distance = vm_utc_tm - host_utc_tm
            # Distance between utc and timezone time in vm
            vm_tz_distance = vm_tz_tm - vm_utc_tm
            logging.debug("\nUTC distance:%s\n"
                          "VM timezone distance:%s\n"
                          "Expected UTC distance:%s\n"
                          "Expected VM timezone distance:%s",
                          utc_distance, vm_tz_distance,
                          utc_span, vm_tz_span)
            # Check UTC time
            if abs(utc_distance - utc_span) > delta:
                fail_info.append("UTC time between host and %s do not match."
                                 % vm.name)
            # Check timezone time of vm
            if abs(vm_tz_distance - vm_tz_span) > delta:
                fail_info.append("Timezone time of %s is not right." % vm.name)

        # Useless, so shutdown for cleanup
        vm.destroy()

    if stress_type is not None:
        unload_stress(stress_type, params)

    if len(fail_info):
        raise error.TestFail(fail_info)


def test_banned_timer(vms, params):
    """
    Test setting timer's present to no in vm's xml.
    """
    banned_timer = params.get("banned_timer")
    for vm in vms:
        if vm.is_dead():
            vm.start()
        vm.wait_for_login()
        if banned_timer not in get_avail_clksrc(vm):
            raise error.TestNAError("Not supported timer for vm %s" % vm.name)
        vm.destroy()

    set_xml_clock(vms, params)

    start_error = "yes" == params.get("timer_start_error", "no")
    fail_info = []
    # Logging vm to verify whether setting is work
    for vm in vms:
        try:
            vm.start()
            vm.wait_for_login()
            if start_error:
                fail_info.append("Start succeed, but not expected.")
        except virt_vm.VMStartError, detail:
            if start_error:
                logging.debug("Expected failure: %s", detail)
            else:
                raise error.TestFail(detail)

    if start_error:
        if len(fail_info):
            raise error.TestFail(fail_info)
        else:
            return

    # Set vms' clocksource(different vm may have different sources)
    # (kvm-clock tsc hpet acpi_pm...)
    for vm in vms:
        # Get available clocksources
        avail_srcs = get_avail_clksrc(vm)
        if not avail_srcs:
            fail_info.append("Get available clocksources of %s "
                             "failed." % vm.name)
            continue
        logging.debug("Available clocksources of %s:%s", vm.name, avail_srcs)

        if banned_timer in avail_srcs:
            fail_info.append("Timer %s set present to no is still available "
                             "in vm." % banned_timer)
            continue

        # Try to set banned timer
        if set_current_clksrc(vm, banned_timer):
            time.sleep(2)
            if get_current_clksrc(vm) == banned_timer:
                fail_info.append("Set clocksource %s in vm successfully,"
                                 "but not expected." % banned_timer)

    if len(fail_info):
        raise error.TestFail(fail_info)


def test_windows_timer(vms, params):
    """
    Test timers for windows.
    """
    host_tz = params.get("host_timezone", "Asia/Tokyo")
    vm_tz = params.get("vm_timezone", "America/New_York")
    clock_tz = params.get("clock_timezone", "Asia/Shanghai")
    host_tz_vector = convert_tz_to_vector(host_tz)
    vm_tz_vector = convert_tz_to_vector(vm_tz)
    set_tz_vector = convert_tz_to_vector(clock_tz)
    if ((host_tz_vector is None) or (vm_tz_vector is None)
            or (set_tz_vector is None)):
        raise error.TestError("Not supported timezone to convert.")
    delta = int(params.get("allowd_delta", "300"))

    # Confirm vm is down for editing
    for vm in vms:
        if vm.is_alive():
            vm.destroy()

    # Config clock in VMXML
    set_xml_clock(vms, params)

    # Logging vm to set time
    for vm in vms:
        vm.start()
        vm.wait_for_login()
        set_windows_timezone(vm, params.get("vm_timezone"))

    # Set host timezone
    set_host_timezone(params.get("host_timezone"))

    # Get expected utc distance between host and vms
    # with different offset(seconds)
    offset = params.get("clock_offset", "utc")
    # No matter what utc is, the timezone distance
    vm_tz_span = vm_tz_vector * 3600
    host_tz_span = host_tz_vector * 3600
    if offset == "utc":
        utc_span = 0
    elif offset == "localtime":
        utc_span = host_tz_vector * 3600
    elif offset == "timezone":
        utc_span = set_tz_vector * 3600
    elif offset == "variable":
        utc_span = int(params.get("clock_adjustment", 3600))

    # TODO: It seems that actual timezone time in vm is only based on
    # timezone on host. I need to confirm whether it is normal(or bug)
    vm_tz_span = utc_span - host_tz_span

    # To track failed information
    fail_info = []

    # Set vms' clocksource(different vm may have different sources)
    # (kvm-clock tsc hpet acpi_pm...)
    for vm in vms:
        # Get windows vm's time(timezone)
        vm_tz_tm = get_vm_time(vm, "tz", windows=True)
        # Get host's utc time
        host_utc_tm = int(time.time())

        logging.debug("\nTimeZone time in vm:%s\n"
                      "UTC time on host:%s\n",
                      vm_tz_tm, host_utc_tm)

        # Check got time
        # Distance between utc time on host and timezone time in vm
        vm_tz_distance = vm_tz_tm - host_utc_tm
        logging.debug("\nVM timezone distance:%s\n"
                      "Expected VM timezone distance:%s",
                      vm_tz_distance, vm_tz_span)
        # Check timezone time of vm
        if abs(vm_tz_distance - vm_tz_span) > delta:
            fail_info.append("Timezone time of %s is not right." % vm.name)

        # Useless, so shutdown for cleanup
        vm.destroy()

    if len(fail_info):
        raise error.TestFail(fail_info)


def run(test, params, env):
    """
    Test vms' time according timer management of XML configuration.
    """
    timer_type = params.get("timer_type", "all_timers")
    vms = env.get_all_vms()
    if not len(vms):
        raise error.TestNAError("No available vms")

    testcase = globals()["test_%s" % timer_type]
    try:
        testcase(vms, params)
    finally:
        for vm in vms:
            vm.destroy()
        # Reset all vms to utc time
        recover_vm_xml(vms)
