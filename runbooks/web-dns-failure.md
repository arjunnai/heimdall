# Live web DNS resolution failure

An allow-listed hostname returning NXDOMAIN or no public addresses is a live DNS failure signal.
Check authoritative nameservers, delegation, DNSSEC, and recent record changes from an independent
resolver. Private, loopback, link-local, metadata, reserved, and otherwise non-public answers are
refused as scope violations rather than followed. Do not infer a deployment from DNS evidence.
