#!/usr/bin/env python3
"""Hermes Gate Entry Point"""

from hermes_gate.app import HermesGateApp


def main():
    app = HermesGateApp()
    app.run(mouse=False)


if __name__ == "__main__":
    main()
