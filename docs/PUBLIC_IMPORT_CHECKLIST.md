# Public import checklist

Base package: `Saba_Accounting_Development_0_6_5_SECURITY_HARDENED.zip`.

Before publishing source, exclude `docs/reference/`, third-party extracted manuals, customer data, databases, backups, secrets, private keys, built ZIP archives, and caches. Check ownership/license of images, fonts, and all other assets. The repository is public.

Run tests after import with the project's supported Python environment. Build a Windows EXE and verify it on Windows before claiming an installable release.

Current status: reviewed 0.6.5 source imported on `develop`; local compile and 180-test suite pass. Windows CI result is tracked by the commit's Actions run.

