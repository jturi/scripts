# https://github.com/microsoft/terminal$string = 'something'
# https://scoop.sh/

# Install scoop if not installed
try { scoop info }
catch { 
    "Scoop is not installed."
    "Intalling scoop now."
    Set-ExecutionPolicy RemoteSigned -scope CurrentUser
    Invoke-Expression (New-Object System.Net.WebClient).DownloadString('https://get.scoop.sh')
    }
# Install applications
finally {
    $string = $(scoop info)
    # [bool]$string
    if ($string) {
        "Scoop installed."
        "Installing appications with scoop..."
        # Install git
        scoop install git
        # Add bucket for more packages
        scoop bucket add extras
        # Install packages
        scoop install 7zip Audacity autohotkey brave calibre conemu copyq discord ditto firefox cmder foxit-reader curl git googlechrome greenshot obs-studio irfanview   make meld openhardwaremonitor putty python qbittorrent screentogif totalcommander vlc vscode winscp
        # List installed packages
        scoop list
        }
}
