# Read Before Buying a Kärcher Home Robots Vacuum

This document summarises why the RCV5 looked like a trustworthy choice, what Kärcher claims, and what independent investigation actually found. All findings are documented in detail in [INVESTIGATION.md](INVESTIGATION.md).

> **Disclaimer:** This document reflects personal experience and independent technical research. It is not legal or professional advice. Factual claims are supported by referenced evidence; opinions are clearly identified as such.

---

## Why It Looked Like a Good Buy

Two things set the RCV5 apart from competing products at the time of purchase:

### Privacy — a European company with servers in Germany

Most robot vacuums in this price range are Chinese-branded products (Roborock, Dreame, Ecovacs) with data processed in China. The RCV5 appeared to be different: Kärcher is a well-known German brand, and their marketing explicitly states that all data is transferred to servers located in Germany only. For a device with a camera that operates throughout the home, data residency was a deciding factor.

### Service network — physical support across Europe

Kärcher has an established service and repair network across Europe. For a high-value product with moving parts and sensors, having access to authorised repair centres — rather than relying on mail-in warranty with a distant manufacturer — was a meaningful advantage over Chinese-direct brands.

---

## What Kärcher Tells You

### Privacy & data
- *"The entire data transfer between the Home Robots app on your smartphone and your robotic vacuum cleaner and mop runs via a cloud to servers located in Germany only."*
- *"Kärcher places great importance on data protection."*
- Camera and video are processed exclusively on-device — images are never uploaded.

### Security
- *"Regular updates improve security, constantly updated to match current specifications."*

### Product
- AI-powered 3D obstacle avoidance using a camera and depth sensor.
- LiDAR mapping with room segmentation and selective cleaning.

---

## What Investigation Found

### The "Germany only" claim is false — confirmed by Kärcher

Kärcher's Data Protection Team confirmed in writing (March 2026):

> European customer data is stored on AWS within the EEA — not Germany specifically.

The marketing claim is materially inaccurate. At least one documented purchasing decision was made partly on the basis of this claim. Kärcher has not corrected it as of March 2026.

### The entire product stack is Chinese

The firmware, cloud infrastructure, app, and OTA update system are authored and operated by **3iRobotix Co. Ltd.**, a Chinese company. Kärcher is an OEM customer. Kärcher has no independent technical visibility into or control over firmware content, OTA updates, or cloud operations.

China's **National Intelligence Law (2017, Art. 7)** requires any Chinese organisation to support and cooperate with state intelligence work. This obligation applies to 3iRobotix regardless of where data is stored or what contracts exist between Kärcher and 3iRobotix. Standard Contractual Clauses are instruments of EU law and cannot override Chinese domestic legal obligations.

### The camera claim cannot be verified — by anyone

The on-device-only camera processing claim is stated in Kärcher's privacy policy. Kärcher cannot audit or enforce it: the firmware is written and updated by 3iRobotix, and any OTA update could change this behaviour. Kärcher has not responded to questions about what technical mechanism prevents video from being transmitted off-device.

### The device does not work without the cloud

There is no local control API. The robot is non-functional if 3iRobotix cloud services are unavailable. Customers have no contractual relationship with 3iRobotix and no recourse if service is degraded or discontinued.

---

## Actual User Experience (Two Robots)

The following issues were observed over the ownership period with two identical RCV5 units.

### App quality

The app looks, feels, and functions like a neglected product. It is well below expectations for a modern consumer device in this price range. Feature depth is noticeably behind competing vacuums — including cheaper Chinese-branded alternatives.

### Session expiry

The app requires regular re-login as sessions expire without warning. For older users or anyone who does not use the app frequently, this is a significant usability problem.

### Robot went offline mid-clean

One unit went offline and stopped during a cleaning session and required a full factory reset to become operational again. No error was surfaced in the app during or after the failure.

### Room names reset regularly

Room names assigned in the app reset on their own, requiring repeated manual re-entry.

### Privacy setting resets

The option to disable uploading of cleaning records resets regularly. After each reset, cleaning data is uploaded until the user notices and opts out again.

### Login broke silently

At one point, login stopped working entirely with no error message or indication of what was wrong. The cause: Kärcher had changed their password validation rules, making existing passwords invalid. The app silently failed rather than prompting the user to update their password or explaining what was wrong.

### One software update in the entire ownership period

Kärcher claims regular security and feature updates. In practice, a single firmware update was observed across the full ownership period. App Store reviews going back two years describe the same categories of bugs — with no visible improvement.

### Feedback goes nowhere

Feedback submitted through the in-app feedback mechanism received no acknowledgement and no follow-up.

### Verdict

The two primary reasons to choose this robot over cheaper alternatives — European data residency and Kärcher's brand trust — proved false or misleading. Given that, the case for choosing this product over alternatives is significantly weakened.

---

## What Kärcher Has Not Answered (as of March 2026)

Four questions were put to Kärcher in writing after their initial response:

1. Will Kärcher correct its "Germany only" marketing materials?
2. Does Kärcher conduct independent technical audits of 3iRobotix firmware before OTA distribution to EU customers?
3. What technical mechanism prevents 3iRobotix firmware from transmitting video off-device?
4. Is `eu-cdndevaiot.3irobotix.net` a development environment serving EU production devices?

None have been answered.

---

## Summary

| Claim | Status |
|---|---|
| Servers in Germany only | **FALSE** — confirmed by Kärcher's own DPO |
| Kärcher controls the technology | **FALSE** — 3iRobotix (China) controls firmware, cloud, and OTA |
| Camera processed on-device only | **UNVERIFIABLE** — depends entirely on 3iRobotix firmware |
| Regular security updates | **UNVERIFIABLE** — no independent audit documented |
| GDPR compliance | **TRUE** — formally in place, but SCCs cannot override Chinese law |

Full technical detail: [INVESTIGATION.md](INVESTIGATION.md)
