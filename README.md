# Attendo Sync

<div align="center">

🏢 **Employee Attendance Tracking & Payroll System** 📊

A desktop application that syncs data from ESSL biometric devices, calculates attendance patterns, computes daily wages, and provides visual analytics.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

</div>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Usage Guide](#usage-guide)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

---

## 🎯 Overview

Attendo Sync is an intelligent attendance management solution designed for small to medium-sized organizations using ESSL biometric attendance devices. It automates the entire workflow:

1. **Data Collection**: Fetches attendance records directly from ESSL devices via TCP/IP
2. **Intelligent Processing**: Applies logic for split shifts, detects anomalies, and flags irregularities
3. **Payroll Calculation**: Computes daily wages based on hours worked and customized hourly rates
4. **Visual Analytics**: Provides interactive dashboards with trend analysis
5. **Cloud Sync**: Automatic backup to Google Drive folders

The application runs locally on Windows machines and requires no internet connection for core functionality.

---

## ✨ Features

### Core Functionality

| Feature | Description |
|---------|-------------|
| **Auto-Fetch Attendance** | One-click retrieval from ESSL devices on local network |
| **Smart Split-Shift Logic** | Automatically separates morning and afternoon punch-ins/outs around noon |
| **Anomaly Detection** | Flags unusual patterns like very short days, excessive hours, or same-second punches |
| **Daily Wage Calculation** | Computes pay based on configurable hourly rates (per employee or default) |
| **Dual Database Storage** | Separate databases for attendance and payroll data |
| **Google Drive Sync** | Automatic backup to specified synced folder |
| **Interactive Dashboards** | Real-time charts showing hours trends and excess/deficit analysis |

### Advanced Features

- ✅ Employee-specific drill-down views
- ✅ Monthly summary calculations
- ✅ Equivalent full-day conversions
- ✅ Weekend activity flagging
- ✅ Export-friendly data structure
- ✅ Configurable workday standards
- ✅ Persistent settings across sessions

---

## 💻 System Requirements

### Hardware

- **Processor**: Intel Core i3 or equivalent (i5 recommended)
- **RAM**: 4 GB minimum (8 GB recommended)
- **Storage**: 500 MB free space
- **Network**: Local network connectivity to ESSL device (Ethernet required)

### Software

- **Operating System**: Windows 10 or later (64-bit)
- **Python**: Version 3.8 or higher
- **.NET Framework**: 4.7.2 or later
- **Device SDK**: ZKFace/ZKTime library compatible with your ESSL device

### Network Configuration

- Device IP must be accessible from the host machine
- Standard port: `4370` (customizable)
- Firewall rules must allow outbound TCP on configured port
- Same subnet recommended for optimal performance

---

## 🚀 Installation

### Quick Start (Recommended)

1. **Clone Repository**
   ```bash
   git clone https://github.com/bijoyantonypt/Attendance.git
   cd Attendance/Attendo_Sync
