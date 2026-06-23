"""Cloud-folder share adapters (OneDrive delivery).

- ``LocalShareAdapter`` — active today; operates on a local directory tree
  (the machine's OneDrive sync root) and mints ``file://`` links.
- ``OneDriveGraphAdapter`` — deferred stub; talks to Microsoft Graph once an
  Azure AD app registration is available.
"""
