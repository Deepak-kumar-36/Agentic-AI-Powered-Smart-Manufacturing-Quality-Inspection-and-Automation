# Document 01 — Project Charter & Execution Roadmap

**Project:** DIY Agentic AI Smart Manufacturing Quality Inspection Prototype  
**Version:** 1.0  
**Date:** 15 October 2026  
**Status:** Initial build baseline

## 1. Purpose

- This document establishes the first buildable version of the project: a physical tabletop inspection station connected to a real computer-vision pipeline.
- The prototype must demonstrate the full loop: detect an item, capture an image using a borrowed phone, run the selected training model on a laptop, record PASS / FAIL / UNVERIFIED, and operate a physical indicator and a servo-driven reject arm.
- This is a prototype engineering baseline, not a claim of production certification. The Production-Grade PRD v3.0 remains the target-state reference.

## 2. Agreed decisions

- Physical hardware is required; a software-only dashboard is not sufficient.
- Use a borrowed phone as the camera initially. Select the streaming method after testing the phone and laptop.
- Use an existing laptop/PC for inference. Do not buy a dedicated AI computer before benchmarking.
- Build a small DIY conveyor with a frame, rollers, flexible belt, and a separate DC geared motor.
- Use an ESP32-class microcontroller to read the presence sensor and control indicators, servo, and motor-driver interface.
- Use a small servo-driven flap/arm to divert lightweight test objects into a reject tray.
- Choose the product/defect category after inspecting the available training data and current model. Keep interfaces configurable.
- Initially stop the belt during capture and inference. Resume after a terminal decision or explicit manual resolution of UNVERIFIED.
- Prefer local-network or USB communication. Core inspection must not require cloud connectivity.
- Keep the build low-voltage and tabletop-scale. Do not connect it to industrial machinery or safety-critical PLC circuits.

## 3. Acceptance criteria

- AC-01: A physical object is detected at the inspection point.
- AC-02: The phone provides a usable image to the laptop through a documented, repeatable method.
- AC-03: The inference service returns a structured result with decision, score, model/version, timestamp, and reason code.
- AC-04: PASS, FAIL, and UNVERIFIED are distinct. Image/model errors must never silently become PASS.
- AC-05: The laptop sends a bounded command to the ESP32, which acknowledges it.
- AC-06: PASS turns on green indication and does not activate the reject servo.
- AC-07: FAIL turns on red indication and activates the reject mechanism once for the associated item.
- AC-08: UNVERIFIED turns on amber indication and waits for manual resolution; no automatic accept/reject by default.
- AC-09: The belt remains stopped while inspection and reject movement occur.
- AC-10: Retries or duplicate messages cannot trigger the same reject action twice.
- AC-11: An accessible operator stop/power-disconnect method exists.
- AC-12: The demonstration works locally without cloud access.

## 4. Non-goals for the first prototype

- No direct connection to a factory PLC, industrial conveyor, actuator, or safety circuit.
- No claim of industrial accuracy, safety certification, or guaranteed defect detection.
- No autonomous LLM control of motors, servos, or other physical actuators.
- No Jetson or industrial camera purchase until measured requirements justify it.
- No final product-category commitment before inspecting the available model and training data.
- No multi-factory fleet management, billing, or enterprise deployment in the first hardware milestone.

## 5. System overview

- Phone camera → local capture/stream adapter → laptop inference service → deterministic inspection policy → inspection event store/UI → bounded controller command → ESP32 → indicators/servo/motor driver.
- The laptop is the decision authority. The ESP32 performs only explicitly defined commands and reports execution status; it does not interpret model scores or make quality decisions.
- The belt motor must be driven through a suitably rated motor driver. Do not power the motor or servo directly from an ESP32 GPIO pin.

## 6. Required document sequence

- Document 01 (this document): Project charter, scope, acceptance criteria, and execution order.
- Document 02: Hardware bill of materials, mechanical design, power budget, wiring, and pin map.
- Document 03: Software architecture and repository audit; identify existing frontend, API, inference service, and model code before changing anything.
- Document 04: Dataset/model qualification plan: training data, artifacts, preprocessing, thresholds, and inference inputs.
- Document 05: Phone-camera capture and local streaming specification.
- Document 06: ESP32 firmware specification and command/acknowledgement protocol.
- Document 07: Laptop inference service, deterministic decision policy, and inspection event schema.
- Document 08: Hardware integration and conveyor/servo state-machine specification.
- Document 09: Dashboard and operator workflow specification.
- Document 10: Test plan, fault injection, acceptance checklist, and demo script.
- Document 11: Setup, calibration, troubleshooting, and operator guide.
- Document 12: Production transition checklist mapping prototype gaps to the production PRD.

## 7. Milestones

- M0 — Inventory: locate repository, model files, available phone/laptop/ESP32, and tools. Avoid nonessential purchases.
- M1 — Model verified: run inference on a known sample and document actual output/runtime.
- M2 — Camera verified: capture a stable phone image on the laptop.
- M3 — Electronics bench test: read sensor and operate indicators/servo with conveyor disconnected.
- M4 — Conveyor bench test: safely run/stop belt through the motor driver.
- M5 — Integrated loop: sensor → capture → inference → decision → physical output.
- M6 — Repeatability: test a batch; verify logs, duplicate protection, error handling, and safe stop.
- M7 — Demonstration-ready: assemble frame, label wiring, prepare samples, and rehearse.

## 8. Implementation rules

- Make small, testable changes and keep a known-good version at every milestone.
- Do not restructure existing services until the repository audit establishes what exists.
- Separate model inference and decision policy from hardware control.
- Use explicit timeouts, bounded retries, unique inspection IDs, and idempotency keys for commands.
- Log each inspection decision and each physical action request/acknowledgement with correlated IDs.
- Missing image, camera timeout, model error, invalid score, or controller timeout must become UNVERIFIED/fault—not PASS.
- Never activate hardware from free-form text or an LLM-generated command.
- Keep mechanical tests low-speed, lightweight, supervised, and guarded where practical.

## 9. Open items for inventory

- Exact laptop OS, runtime versions, and whether the current repository builds.
- Exact model implementation and whether trained PatchCore artifacts load successfully.
- Phone model and support for local streaming or USB webcam mode.
- ESP32 board variant and available power supply.
- Motor voltage/current, belt dimensions, roller diameter, and test-object mass.
- Whether laptop/controller communication will use Wi-Fi or USB serial.
- Product category and training dataset, to be decided after inspecting available assets.

## 10. Definition of done

- The team agrees on system boundaries, physical workflow, non-goals, acceptance criteria, and document order.
- No expensive edge computer or industrial camera is purchased before a measured need is established.
- Next step: inventory/repository audit and Document 02 hardware design.

