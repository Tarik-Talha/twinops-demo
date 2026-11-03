# TwinOps — Embroidery Factory Pilot

A production-planning and digital-twin project for comparing reference and optimized schedules under machine, operator, hoop, batch, and shift constraints.

Developed by Tarık. This portable repository preserves the existing FT06-based architecture and keeps the original local project unchanged.

## Run

Python 3.12 is the tested version:

```sh
python -m venv .venv
```

Activate with `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on macOS/Linux, then:

```sh
python -m pip install -r requirements.txt
python -m streamlit run embroidery_pilot/app.py
```

The Streamlit entry point for hosting is `embroidery_pilot/app.py`.

## Try the demo

1. Inspect the synthetic scenario and FIFO reference plan.
2. Calculate the CP-SAT plan and compare both plans using the same input.
3. Inspect the batch timeline and the production state at a selected time.
4. Change an assumption or upload a valid scenario. Apply changes to recalculate the reference and clear stale optimization results.
5. Download the applied scenario, validated plan, or OpenUSD scene.

Each browser session writes its own artifacts. One visitor's selected plan and generated preview do not replace another visitor's artifacts.

## Blender

Blender is optional for running the planning demo. To build a baked `.blend` scene and preview, install Blender and put it on your executable path, or set `TWINOPS_BLENDER` to its executable. The build button is disabled when Blender is unavailable. OpenUSD export remains available.

```sh
python -m embroidery_pilot.validate --build-blender
```

`ft06_pilot/` contains the preserved helper modules reused by the embroidery module. The Blender bridge and generated scene are checked separately from the Streamlit interface.

## Verify

```sh
python -m unittest discover -s embroidery_pilot -t . -p "test_*.py" -v
python -m embroidery_pilot.validate
```

Checks cover multi-head batches, shift calendars, shared resources, sequential Tajima stages, schedule feasibility, SimPy replay, scenario validation, stale UI results, and independent browser sessions.

## What the numbers mean

The included orders, effective speeds, and production times are synthetic scenario inputs. In the disclosed example, both plans complete 261 products at 16:00, while total order lateness changes from 234 to 0 minutes. This is a scheduling demonstration, not measured production growth or verified financial savings.

Machine inventory and the modeled 09:00–17:00 shift originate from the project owner's factory description. Layout and machine geometry are conceptual. Real calibration and cost inputs are required before claiming operational or financial results.

## Portable-release changes

- Bundled the embroidery module and the FT06 helpers it uses.
- Added pinned dependencies and a portable launcher without a workstation-specific fallback.
- Isolated generated artifacts and previews per browser session.
- Made the optional Blender dependency explicit in the interface.
- Added release regression tests and GitHub Actions configuration.
