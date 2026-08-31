# Live web TLS certificate expiry

A validated peer certificate with 30 or fewer days remaining should trigger certificate-owner
notification and renewal verification. Confirm the served certificate from another public vantage
point, check the complete chain, and verify renewal automation. A probe failure is not proof of
expiry. Heimdall's live adapter diagnoses and cites the observation but cannot renew certificates.
