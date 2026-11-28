---
name: solidworks-mechanical
description: Build and verify editable SolidWorks parts, mated assemblies, native explode steps, and engineering drawings via local COM and structured CAD jobs.
---

# OmniSolidWorks V1.0.1-RC1

1. Use Windows x64 Python 3.12 or later and Windows PowerShell 5.1. Run `python -B scripts/v03_jobs.py --preflight` from this Skill folder. Use an empty session and select the intended PID when several SolidWorks sessions are running. Live checks passed on SolidWorks 2014 x64 SP0 (COM 22.0.0). SolidWorks 2024 is pending live validation. SolidWorks 2026 compatibility cases passed simulation and await external live testing.
2. Derive dimensions, mate requirements and checks from confirmed project inputs. Submit the job through `scripts/v03_jobs.py`. Use local COM for native CAD work and preserve source files and unrelated open documents.
3. Check native geometry, affected mates, references and drawing data after saving, closing and reopening. For qualified assemblies, verify exploded movement and return to the folded state. Report static solid interference, continuous AABB broad-phase findings and any remaining freedoms separately.
4. For disassembly documentation use editable native explode steps, drawing balloons and a separate step table. Route-line persistence is experimental and failed G06. After a host failure, preserve verified checkpoints and resume on a confirmed empty session.

[Installation](README.en.md#installation) · [Patch acceptance](ACCEPTANCE_REPORT.md) · [Setup and troubleshooting](ENVIRONMENT_COMPATIBILITY.md) · [Job guide](docs/V03_GUIDE.md) · [Exploded assembly workflow](docs/EXPLODED_VIEW_GUIDE.md) · [Recovery](docs/INCREMENTAL_GUIDE.md) · [Acceptance scope](FINAL_ASSESSMENT.md)
