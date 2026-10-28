"""Install/remove only DVP's XDG desktop startup entry, preserving other entries."""
import argparse
import os
from pathlib import Path

def desktop_quote(value):
    # Desktop Entry Exec has its own escaping rules, not shell quoting.
    value = str(value)
    if any(char in value for char in ('\n','\r','=')):
        raise ValueError('The installation path cannot contain a newline or equals sign')
    value = value.replace('%','%%').replace('\\','\\\\\\\\')
    for char in ('"',chr(96),'$'):
        value = value.replace(char,'\\\\'+char)
    return '"'+value+'"'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('enable','disable'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    base = Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    target = base/'autostart/dvp.desktop'
    legacy = base/'autostart/dvp-pi5.desktop'
    if args.action=='disable':
        target.unlink(missing_ok=True)
        legacy.unlink(missing_ok=True)
        print('DVP autostart disabled.')
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    legacy.unlink(missing_ok=True)
    target.write_text('[Desktop Entry]\nType=Application\nName=DVP\n'
                      'Comment=USB camera, detection, recording and HDMI display\n'
                      'Exec='+desktop_quote(root/'start_dvp.sh')+'\n'
                      'Terminal=false\nStartupNotify=false\n'
                      'X-GNOME-Autostart-enabled=true\n'
                      'X-GNOME-Autostart-Delay=0\n',encoding='utf-8')
    print('DVP desktop autostart enabled:',target)
    print('Enable display-session autologin if needed.')

if __name__=='__main__':
    main()
