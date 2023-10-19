<!-- <img src="./assets/coa_tools_logo.png" width="250"> -->

# COA tools 2

the Addon of Cutout Animation Tools for Blender, which allows you to create cutout animations in Blender.

[![GitHub release](https://img.shields.io/github/release/Aodaruma/coa_tools2.svg)](https://github.com/Aodaruma/coa_tools2/releases)

## Table of Contents

- [Description](#description)
- [Download and Installation](#download-and-installation)
  - [Photoshop Exporter](#photoshop-exporter)
  - [GIMP Exporter](#gimp-exporter)
  - [KRITA Exporter](#krita-exporter)
  - [Blender Addon](#blender-addon)
- [Development](#development)

## Description

COA Tools 2 is an add-on developed by [ndee89](https://github.com/ndee85) and modified/remade by Aodaruma, which enables 2D rigging and animation within Blender.

[The original COA Tools by ndee89](https://github.com/ndee85/coa_tools) provided a rapid workflow for creating 2D cutout characters/animations in Blender. With COA Tools 2, the goal is to support Blender 3.4 and above, introduce automatic mesh generation, and establish a workflow with minimal features, allowing direct editing without going through proprietary modes.

Currently, the focus for development is on two aspects:

1. Photoshop sprite exporter
2. Blender add-on

The intention is to concentrate on these areas, specifically addressing the necessary improvements.

Since development is a time and resource-intensive process, it's not easy to being solely undertaken by me. However, if there are multiple developers willing to contribute and if the project necessitates scalability, I am considering inviting collaborators to join :)

## Download and Installation

### Download

Download the latest release from the [releases page](https://github.com/Aodaruma/coa_tools2/releases).


### Installation

#### Photoshop Exporter

The .jsx file has to be copied into the photoshop scripts folder which is located in: `C:\Program Files\Adobe\Adobe Photoshop CC 2015\Presets\Scripts`

Don’t forget to restart Photoshop and then go to File -> Scripts -> BlenderExporter.jsx

#### GIMP Exporter

The coatools_exporter.py should be copied to your GIMP plug-ins folder which is located in:

It should show up under Files>Export to CoaTools... after your restart GIMP

It should show up under Files>Export to CoaTools... after your restart GIMP

#### KRITA Exporter

The coa_tools2_exporter folder and coa_tools2_exporter.desktop file goes to your pykrita directory.

To find it, go to Krita, Settings/Manage Resources: Click "Open Resource Folder". If this does not show you the Pykrita folder, then create one. Copy 'coa_tools2_exporter' folder and 'coa_tools2_exporter.desktop' from COA_Tools-Master/Krita into that folder. Restart Krita. 
Krita: Settings/Configure Krita -> Python Plugin Manager: Enable COA Tools Exporter. Once activated, enable the docker under Settings/Dockers/COA Tools Exporter.

Select the desired layers. Give it a name and path in the docker and export the images.

#### Blender Addon

Zip the coa_folder.
Go to File -> User Preferences -> Add-ons and click the “Install from file...” button.
This will install and enable the Addon for Blender. Don’t forget to save the user preferences, otherwise the addon will not be activated after restart.

## Development

The source code for development is in the main branch. `coa_tools2` folder is a main body of the add-on. For efficient development, you can create a link to that folder in the Blender `addons` folder.

``` bash
# Linux
LATEST_BLENDER_DIR=$(find "$HOME/.config/blender" -d 1 | grep -e "[0-9]\.[0-9]" | sort -rh | head -n 1)
ln -s "$PWD/coa_tools2" "$LATEST_BLENDER_DIR/scripts/addons/coa_tools2"
```

``` bash
# macOS
LATEST_BLENDER_DIR=$(find "$HOME/Library/Application Support/Blender" -d 1 | grep -e "[0-9]\.[0-9]" | sort -rh | head -n 1)
ln -s "$PWD/coa_tools2" "$LATEST_BLENDER_DIR/scripts/addons/coa_tools2"
```

```powershell
# Windows PowerShell
$LatestBlenderDir = (Get-ChildItem "$env:APPDATA\Blender Foundation\Blender" -Directory | Where-Object { $_.Name -match "[0-9]\.[0-9]" } | Sort-Object -Descending | Select-Object -First 1).FullName
New-Item -ItemType Junction -Path "$LatestBlenderDir\scripts\addons\coa_tools2" -Value "$(Get-Location)\coa_tools2"
```

I'm using pipenv for dependency management. You can install the dependencies with `pipenv sync` if you have already installed pipenv.

Some extensions of vscode are recommended for development and written in `.vscode/extensions.json`. Feel free to use them.
