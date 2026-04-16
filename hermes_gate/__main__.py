#!/usr/bin/env python3
"""Hermes Gate 入口命令"""
from hermes_gate.app import HermesGateApp

def main():
    app = HermesGateApp()
    app.run()

if __name__ == "__main__":
    main()
