---
title: Incident Postmortem - Skyline Wheel Stall
classification: confidential
---
# Incident Postmortem: Skyline Wheel Stall, September 14

## Summary
The Skyline Wheel stopped with gondolas loaded. 42 guests were evacuated in 55 minutes. There were no
injuries.

## Root cause
A controller firmware watchdog reset the drive during a routine speed adjustment. The firmware update applied
the week before changed the watchdog timeout.

## Actions
Roll back the firmware, add a manual evacuation drill to the monthly schedule, and require a staged rollout
for controller updates.
