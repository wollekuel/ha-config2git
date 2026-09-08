# ha-config2git

A Home Assistant App (formerly known as Add-on) that watches the Home Assistant
configuration directory, versions changes with Git, and pushes them to a GitHub
repository over SSH.

> **Status:** Early development. This repository currently contains the
> application skeleton only. The Python implementation is added in a later phase.

## Planned functionality

- Watch `/config` for changes to configuration files (`.yaml`, `.yml`, `.json`,
  `custom_components/`, `blueprints/`, `esphome/`).
- Sync relevant files into a local Git repository under `/data/repository`.
- Commit and push changes to a configured GitHub repository via SSH
  (dedicated deploy key).

## How it runs

The app is a native Home Assistant App: a Docker container built from a
`Dockerfile` and managed by the Home Assistant Supervisor.

## Installation

_Not yet installable - the app is under development._
