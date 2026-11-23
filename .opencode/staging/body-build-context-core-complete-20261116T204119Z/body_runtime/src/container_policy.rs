use std::collections::HashSet;
use std::fs;
use std::path::Path;

const REQUIRED_TMPFS_MOUNTS: [(&str, u64); 10] = [
    ("/dev/shm", 8 * 1024 * 1024),
    ("/tmp", 32 * 1024 * 1024),
    ("/opt/aios_rebuild/data_core/FractalCache", 32 * 1024 * 1024),
    ("/opt/aios_rebuild/data_core/log", 8 * 1024 * 1024),
    ("/opt/aios_rebuild/dream_core/state", 16 * 1024 * 1024),
    ("/opt/aios_rebuild/memory", 16 * 1024 * 1024),
    ("/opt/aios_rebuild/marketplace_core/config", 8 * 1024 * 1024),
    ("/opt/aios_rebuild/music_core/config", 8 * 1024 * 1024),
    (
        "/opt/aios_rebuild/music_core/music_library",
        8 * 1024 * 1024,
    ),
    ("/opt/aios_rebuild/template_core/config", 8 * 1024 * 1024),
];

const SYSTEM_MOUNTS: [(&str, &str, &str); 15] = [
    ("/", "overlay", "ro"),
    ("/proc", "proc", "rw"),
    ("/dev", "tmpfs", "rw"),
    ("/dev/pts", "devpts", "rw"),
    ("/sys", "sysfs", "ro"),
    ("/sys/fs/cgroup", "cgroup2", "ro"),
    ("/dev/mqueue", "mqueue", "rw"),
    ("/etc/resolv.conf", "ext4", "ro"),
    ("/etc/hostname", "ext4", "ro"),
    ("/etc/hosts", "ext4", "ro"),
    ("/proc/bus", "proc", "ro"),
    ("/proc/fs", "proc", "ro"),
    ("/proc/irq", "proc", "ro"),
    ("/proc/sys", "proc", "ro"),
    ("/proc/sysrq-trigger", "proc", "ro"),
];

const AUXILIARY_SYSTEM_MOUNTS: [(&str, &str, &str); 7] = [
    ("/proc/acpi", "tmpfs", "ro"),
    ("/proc/interrupts", "tmpfs", "rw"),
    ("/proc/kcore", "tmpfs", "rw"),
    ("/proc/keys", "tmpfs", "rw"),
    ("/proc/scsi", "tmpfs", "ro"),
    ("/proc/timer_list", "tmpfs", "rw"),
    ("/sys/firmware", "tmpfs", "ro"),
];

pub fn violations() -> Vec<&'static str> {
    let mut violations = Vec::new();

    match fs::read_to_string("/proc/self/status") {
        Ok(status) if status_is_restricted(&status) => {}
        _ => violations.push("body_runtime_privileges_unverified"),
    }

    match fs::read_to_string("/proc/self/mountinfo") {
        Ok(mountinfo) => {
            if !root_mount_is_read_only(&mountinfo) {
                violations.push("body_runtime_root_not_read_only");
            }
            if !required_tmpfs_mounts_are_bounded(&mountinfo) {
                violations.push("body_runtime_tmpfs_mounts_unverified");
            }
            if !mount_table_is_confined(&mountinfo) {
                violations.push("body_runtime_mount_table_unverified");
            }
        }
        Err(_) => {
            violations.push("body_runtime_root_not_read_only");
            violations.push("body_runtime_tmpfs_mounts_unverified");
            violations.push("body_runtime_mount_table_unverified");
        }
    }

    let interfaces = fs::read_dir("/sys/class/net").ok().and_then(|entries| {
        entries
            .map(|entry| {
                entry
                    .ok()
                    .map(|entry| entry.file_name().to_string_lossy().into_owned())
            })
            .collect::<Option<Vec<_>>>()
    });
    let routes = fs::read_to_string("/proc/net/route").ok();
    match (interfaces, routes) {
        (Some(interfaces), Some(routes)) if network_is_isolated(&interfaces, &routes) => {}
        _ => violations.push("body_runtime_network_not_isolated"),
    }

    match read_cgroup_limits() {
        Some((cpu, memory, swap, pids))
            if cgroup_limits_are_bounded(&cpu, &memory, &swap, &pids) => {}
        _ => violations.push("body_runtime_cgroup_limits_unverified"),
    }

    if !gpu_devices_are_absent() {
        violations.push("body_runtime_gpu_device_present_or_unverified");
    }

    violations
}

fn status_is_restricted(status: &str) -> bool {
    let uid = status_value(status, "Uid:")
        .and_then(|value| value.split_whitespace().next())
        .and_then(|value| value.parse::<u32>().ok());
    let effective_caps = status_value(status, "CapEff:")
        .and_then(|value| u128::from_str_radix(value.trim(), 16).ok());
    let bounding_caps = status_value(status, "CapBnd:")
        .and_then(|value| u128::from_str_radix(value.trim(), 16).ok());
    let no_new_privileges =
        status_value(status, "NoNewPrivs:").and_then(|value| value.trim().parse::<u8>().ok());

    uid == Some(10001)
        && effective_caps == Some(0)
        && bounding_caps == Some(0)
        && no_new_privileges == Some(1)
}

fn status_value<'a>(status: &'a str, key: &str) -> Option<&'a str> {
    status.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        (format!("{name}:") == key).then_some(value)
    })
}

fn root_mount_is_read_only(mountinfo: &str) -> bool {
    mountinfo.lines().any(|line| {
        let Some((mount, _)) = line.split_once(" - ") else {
            return false;
        };
        let fields: Vec<_> = mount.split_whitespace().collect();
        fields.get(4) == Some(&"/")
            && fields
                .get(5)
                .is_some_and(|options| options.split(',').any(|option| option == "ro"))
    })
}

fn required_tmpfs_mounts_are_bounded(mountinfo: &str) -> bool {
    REQUIRED_TMPFS_MOUNTS
        .iter()
        .all(|(mountpoint, expected_size)| {
            let mut matches = mountinfo.lines().filter(|line| {
                line.split_once(" - ")
                    .and_then(|(mount, _)| mount.split_whitespace().nth(4))
                    == Some(*mountpoint)
            });
            let Some(line) = matches.next() else {
                return false;
            };
            if matches.next().is_some() {
                return false;
            }

            let Some((mount, filesystem)) = line.split_once(" - ") else {
                return false;
            };
            let mount_fields: Vec<_> = mount.split_whitespace().collect();
            let filesystem_fields: Vec<_> = filesystem.split_whitespace().collect();
            let mount_options = mount_fields.get(5).copied().unwrap_or("");
            let super_options = filesystem_fields.get(2).copied().unwrap_or("");
            let options: Vec<_> = mount_options
                .split(',')
                .chain(super_options.split(','))
                .collect();
            let actual_size = options.iter().find_map(|option| {
                option
                    .strip_prefix("size=")
                    .and_then(parse_mount_size_bytes)
            });

            filesystem_fields.first() == Some(&"tmpfs")
                && ["rw", "nosuid", "nodev", "noexec"]
                    .iter()
                    .all(|required| mount_options.split(',').any(|option| option == *required))
                && actual_size == Some(*expected_size)
        })
}

fn mount_table_is_confined(mountinfo: &str) -> bool {
    let mut seen = HashSet::new();
    for line in mountinfo.lines() {
        let Some((mount, filesystem)) = line.split_once(" - ") else {
            return false;
        };
        let mount_fields: Vec<_> = mount.split_whitespace().collect();
        let filesystem_fields: Vec<_> = filesystem.split_whitespace().collect();
        if mount_fields.len() < 6 || filesystem_fields.len() < 3 {
            return false;
        }
        let mountpoint = decode_mount_field(mount_fields[4]);
        if !seen.insert(mountpoint.clone()) {
            return false;
        }
        let filesystem_type = filesystem_fields[0];
        let mode = mount_fields[5]
            .split(',')
            .find(|option| *option == "ro" || *option == "rw");
        if let Some((_, expected_type, expected_mode)) = SYSTEM_MOUNTS
            .iter()
            .chain(AUXILIARY_SYSTEM_MOUNTS.iter())
            .find(|(path, _, _)| *path == mountpoint)
        {
            if filesystem_type != *expected_type || mode != Some(*expected_mode) {
                return false;
            }
            if mountpoint == "/" && decode_mount_field(mount_fields[3]) != "/" {
                return false;
            }
            if mountpoint.starts_with("/etc/")
                && !is_docker_generated_config_mount(&mountpoint, mount_fields[3])
            {
                return false;
            }
        } else if !REQUIRED_TMPFS_MOUNTS
            .iter()
            .any(|(path, _)| *path == mountpoint)
            || filesystem_type != "tmpfs"
            || mode != Some("rw")
        {
            return false;
        }
    }

    let expected_paths: HashSet<&str> = SYSTEM_MOUNTS
        .iter()
        .chain(AUXILIARY_SYSTEM_MOUNTS.iter())
        .map(|(path, _, _)| *path)
        .chain(REQUIRED_TMPFS_MOUNTS.iter().map(|(path, _)| *path))
        .collect();
    seen.len() == expected_paths.len() && expected_paths.iter().all(|path| seen.contains(*path))
}

fn decode_mount_field(field: &str) -> String {
    field
        .replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
}

fn is_docker_generated_config_mount(mountpoint: &str, root: &str) -> bool {
    let Some(filename) = mountpoint.strip_prefix("/etc/") else {
        return false;
    };
    let Some(relative) = decode_mount_field(root)
        .strip_prefix("/var/lib/docker/containers/")
        .map(str::to_string)
    else {
        return false;
    };
    let Some((container_id, mounted_file)) = relative.split_once('/') else {
        return false;
    };
    container_id.len() == 64
        && container_id.bytes().all(|value| value.is_ascii_hexdigit())
        && mounted_file == filename
}

fn parse_mount_size_bytes(size: &str) -> Option<u64> {
    if let Some(kibibytes) = size.strip_suffix('k') {
        return kibibytes.parse::<u64>().ok()?.checked_mul(1024);
    }
    size.parse::<u64>().ok()
}

fn network_is_isolated(interfaces: &[String], routes: &str) -> bool {
    interfaces == ["lo"]
        && !routes
            .lines()
            .skip(1)
            .any(|line| line.split_whitespace().nth(1) == Some("00000000"))
}

fn cgroup_limits_are_bounded(cpu: &str, memory: &str, swap: &str, pids: &str) -> bool {
    let cpu_fields: Vec<_> = cpu.split_whitespace().collect();
    cpu_fields.as_slice() == ["100000", "100000"]
        && memory.trim() == "268435456"
        && swap.trim() == "0"
        && pids.trim() == "32"
}

fn read_cgroup_limits() -> Option<(String, String, String, String)> {
    Some((
        fs::read_to_string("/sys/fs/cgroup/cpu.max").ok()?,
        fs::read_to_string("/sys/fs/cgroup/memory.max").ok()?,
        fs::read_to_string("/sys/fs/cgroup/memory.swap.max").ok()?,
        fs::read_to_string("/sys/fs/cgroup/pids.max").ok()?,
    ))
}

fn gpu_devices_are_absent() -> bool {
    if Path::new("/dev/dxg").exists() {
        return false;
    }
    let Ok(mut devices) = fs::read_dir("/dev") else {
        return false;
    };
    devices.all(|entry| {
        entry
            .ok()
            .is_some_and(|entry| !entry.file_name().to_string_lossy().starts_with("nvidia"))
    })
}

#[cfg(test)]
mod tests {
    use super::{
        cgroup_limits_are_bounded, mount_table_is_confined, network_is_isolated,
        required_tmpfs_mounts_are_bounded, root_mount_is_read_only, status_is_restricted,
        AUXILIARY_SYSTEM_MOUNTS, REQUIRED_TMPFS_MOUNTS, SYSTEM_MOUNTS,
    };

    fn confined_mountinfo() -> String {
        let container_id = "a".repeat(64);
        let mut lines = Vec::new();
        for (index, (mountpoint, filesystem, mode)) in SYSTEM_MOUNTS
            .iter()
            .chain(AUXILIARY_SYSTEM_MOUNTS.iter())
            .enumerate()
        {
            let root = if *mountpoint == "/" {
                "/".to_string()
            } else if let Some(filename) = mountpoint.strip_prefix("/etc/") {
                format!("/var/lib/docker/containers/{container_id}/{filename}")
            } else {
                "/".to_string()
            };
            lines.push(format!(
                "{} 25 0:32 {} {} {},relatime - {} {} rw",
                index + 40,
                root,
                mountpoint,
                mode,
                filesystem,
                filesystem
            ));
        }
        for (index, (mountpoint, size)) in REQUIRED_TMPFS_MOUNTS.iter().enumerate() {
            lines.push(format!(
                "{} 25 0:32 / {} rw,nosuid,nodev,noexec,relatime - tmpfs tmpfs rw,size={}k",
                index + 100,
                mountpoint,
                size / 1024
            ));
        }
        lines.join("\n")
    }

    #[test]
    fn requires_non_root_zero_capabilities_and_no_new_privileges() {
        let status = "Uid:\t10001\t10001\t10001\t10001\nCapEff:\t0000000000000000\nCapBnd:\t0000000000000000\nNoNewPrivs:\t1\n";
        assert!(status_is_restricted(status));
        assert!(!status_is_restricted(&status.replace("10001", "0")));
        assert!(!status_is_restricted(
            &status.replace("0000000000000000", "0000000000000001")
        ));
        assert!(!status_is_restricted(
            &status.replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")
        ));
    }

    #[test]
    fn requires_a_read_only_root_mount() {
        let read_only = "36 25 0:32 / / ro,relatime - overlay overlay rw,lowerdir=/layers";
        let read_write = "36 25 0:32 / / rw,relatime - overlay overlay rw,lowerdir=/layers";
        assert!(root_mount_is_read_only(read_only));
        assert!(!root_mount_is_read_only(read_write));
    }

    #[test]
    fn requires_each_declared_tmpfs_to_be_bounded_and_non_executable() {
        let mountinfo = REQUIRED_TMPFS_MOUNTS
            .iter()
            .enumerate()
            .map(|(index, (mountpoint, size))| {
                format!(
                    "{} 25 0:32 / {} rw,nosuid,nodev,noexec - tmpfs tmpfs rw,size={}k",
                    index + 40,
                    mountpoint,
                    size / 1024
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert!(required_tmpfs_mounts_are_bounded(&mountinfo));
        assert!(!required_tmpfs_mounts_are_bounded(
            &mountinfo.replace("nosuid,nodev,noexec", "nosuid,nodev,exec")
        ));
        assert!(!required_tmpfs_mounts_are_bounded(
            &mountinfo.replace("size=32768k", "size=65536k")
        ));
        assert!(!required_tmpfs_mounts_are_bounded(
            &mountinfo.replace("size=8192k", "size=16384k")
        ));
        let without_dev_shm = mountinfo
            .lines()
            .filter(|line| {
                line.split_once(" - ")
                    .and_then(|(mount, _)| mount.split_whitespace().nth(4))
                    != Some("/dev/shm")
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert!(!required_tmpfs_mounts_are_bounded(&without_dev_shm));
    }

    #[test]
    fn requires_the_complete_allowlisted_mount_table() {
        let mountinfo = confined_mountinfo();
        assert!(mount_table_is_confined(&mountinfo));

        let with_extra_read_only_host_mount =
            format!("{mountinfo}\n900 25 0:88 / /workspace ro,relatime - ext4 /dev/sdc rw");
        assert!(!mount_table_is_confined(&with_extra_read_only_host_mount));

        let replaced_host_config = mountinfo.replace(
            "/var/lib/docker/containers/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/hosts /etc/hosts",
            "/mnt/c/Users/Architect/hosts /etc/hosts",
        );
        assert!(!mount_table_is_confined(&replaced_host_config));

        let without_mount = mountinfo
            .lines()
            .filter(|line| !line.contains(" /dev/mqueue "))
            .collect::<Vec<_>>()
            .join("\n");
        assert!(!mount_table_is_confined(&without_mount));
    }

    #[test]
    fn requires_loopback_only_network_without_a_default_route() {
        let route = "Iface Destination Gateway Flags RefCnt Use Metric Mask\nlo 0000007F 00000000 0001 0 0 0 000000FF";
        assert!(network_is_isolated(&["lo".to_string()], route));
        assert!(!network_is_isolated(
            &["lo".to_string(), "eth0".to_string()],
            route
        ));
        assert!(!network_is_isolated(
            &["lo".to_string()],
            &format!("{route}\neth0 00000000 0100000A 0003 0 0 0 00000000"),
        ));
    }

    #[test]
    fn requires_one_cpu_bounded_memory_no_swap_and_pid_limit() {
        assert!(cgroup_limits_are_bounded(
            "100000 100000",
            "268435456",
            "0",
            "32"
        ));
        assert!(!cgroup_limits_are_bounded(
            "max 100000",
            "268435456",
            "0",
            "32"
        ));
        assert!(!cgroup_limits_are_bounded(
            "100000 100000",
            "max",
            "0",
            "32"
        ));
        assert!(!cgroup_limits_are_bounded(
            "100000 100000",
            "268435456",
            "1024",
            "32"
        ));
        assert!(!cgroup_limits_are_bounded(
            "100000 100000",
            "268435456",
            "0",
            "max"
        ));
    }
}
