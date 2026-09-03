How to open DOSCAR / COHP / COOP Plotter
=========================================

No installation needed. No Python, no command line, nothing to set up —
just download and open. Everything the app needs is already bundled inside
it.


macOS
-----

1. You'll have a file named something like `DOSCAR-Plotter-mac.dmg`.
   Double-click it. A small window opens with the app's icon and a shortcut
   to your Applications folder.

2. Drag the app icon onto the Applications shortcut. This copies it there.
   (You can also skip this and just double-click the app directly from this
   window instead — it runs either way. Dragging it into Applications just
   makes it easier to find again later, e.g. via Spotlight.)

3. Open Applications (or press Cmd+Space, type "DOSCAR", and press Return)
   and double-click the app.

4. The first time you open it, macOS will likely say it "cannot be opened
   because it is from an unidentified developer." This is expected — it
   shows up for any app that isn't distributed through the App Store, and
   doesn't mean anything is wrong. To get past it, just once:
   - Right-click (Control-click) the app and choose **Open**.
   - Click **Open** again in the dialog that appears.
   - From then on, it opens normally with a regular double-click.

5. A window opens with the app already running. Nothing else to configure.


Windows
-------

1. You'll have a file named something like `DOSCAR Plotter-windows.zip`.
   Right-click it and choose **Extract All...**, then pick any folder (your
   Desktop or Documents both work fine).

2. Open the extracted folder and double-click `DOSCAR Plotter.exe`.

3. Windows will likely show a blue "Windows protected your PC" screen. This
   is Microsoft SmartScreen's standard warning for any app that isn't from a
   large registered publisher — it doesn't mean anything is wrong. To
   continue:
   - Click **More info**.
   - Click **Run anyway**.

4. The app opens in its own window.

5. If the window opens but the plotting area stays blank: install the free
   Microsoft Edge WebView2 Runtime (almost every Windows 10/11 PC already
   has it, so this is rarely needed):
   https://developer.microsoft.com/microsoft-edge/webview2/


Using the app
-------------

- A dropdown in the top-left corner switches between the **DOSCAR Plotter**
  and the **COHP/COOP Plotter** — both live in this one app.
- Click **Load demo file** in either mode to try it immediately, without any
  of your own data.
- The **Save plot** buttons save the PNG straight to your Downloads folder —
  no extra dialog, no choosing a location.
- Everything runs locally on your computer. Nothing you upload or export is
  sent anywhere.


What "no installation" means here
----------------------------------

Python and every plotting library the app needs are packaged inside the app
file itself — there's nothing separate to download, no setup wizard, and no
admin permissions required to run it. To remove it later, just delete the
app (macOS) or the extracted folder (Windows); there's no separate
uninstaller and nothing else gets left behind beyond the plots you've
chosen to save.
