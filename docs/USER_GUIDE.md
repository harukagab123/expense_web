# Personal Finance Manager — User Guide

## Launch

Open **Personal Finance Manager** from the Start menu or desktop shortcut. The application starts privately on this computer and opens in your default browser. You do not need Terminal, Python, or Node.js.

Opening the shortcut twice reuses the running application instead of starting another copy.

## Your data

Application data is kept separately from installed program files under your Windows local application-data folder:

`PersonalFinanceManager\data`, `storage`, `backups`, `logs`, and `config`.

Updating or normally uninstalling the application preserves this directory. Keep it if you plan to reinstall.

## Backup

Open **Maintenance** and select **Create Backup**. The verified ZIP is saved in the application backup folder and downloaded through your browser. It contains the database, retained source files, and safe local settings. Select **Open Backup Folder** to see local copies.

## Restore

In **Maintenance**, select **Restore Backup**, choose a Personal Finance Manager backup ZIP, and confirm. The application validates the entire archive and creates a safety backup of your current state before replacing anything. Invalid or incompatible archives do not change current data.

## Update

Updates are distributed as versioned setup packages. Close the application, then run the new setup file. The updater invokes a verified automatic backup before replacing application files. It never needs GitHub credentials and does not replace your data directory. If the safety backup fails, installation stops.

## Diagnostics

Select **Export Diagnostic Bundle** under Maintenance when troubleshooting. This report includes health information and sanitized logs. It excludes the database, statements, transactions, account data, balances, and exports.

## Uninstall

Normal uninstall removes the application program and shortcuts. It intentionally preserves your financial data, retained files, and backups in the Windows local application-data folder.
