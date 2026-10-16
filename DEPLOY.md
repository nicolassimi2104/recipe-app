# Putting the Recipe App online (for your phone)

This guide puts a copy of the app on the internet at
`https://YOURNAME.pythonanywhere.com`, locked with a password, so you can use it
on your phone at the shops. Your computer doesn't need to be on.

Wherever you see **YOURNAME**, use your PythonAnywhere username.

---

## Which free host, and why

I checked each host's own website on **2026-10-16**. Free plans change often,
so if something below doesn't match what you see, the website is right and this
page is out of date.

The app keeps recipes in a SQLite file (`recipes.db`). So the key question is
whether that file survives restarts. If it doesn't, your recipes disappear.

| Host | Keeps your recipes (SQLite file survives restarts)? | Free plan limits | Credit card? | Can it reach other websites (for "import from a link")? |
|---|---|---|---|---|
| **PythonAnywhere (Beginner)** ✅ | **Yes**, a normal 512 MB disk | 1 app, always on (no sleeping). App switches off after **1 month** unless you click a button to extend it | No | **Only allow-listed sites.** Most recipe blogs aren't on the list, so "From a link" will usually fail. Pasting JSON still works |
| Render (Free) | **No**: "Free web services cannot" attach a disk, and files are lost on restart, redeploy or sleep | Sleeps after 15 min idle and takes about 1 min to wake. 750 hours/month | No | Yes (only email ports blocked) |
| Railway (Free) | Yes, a 0.5 GB volume | $5 trial for 30 days, then **$1 credit/month**. That isn't enough to keep even a small app running all month | Not for the trial | Restricted until your account is verified |
| Fly.io | Yes, volumes | **No free plan** for new accounts. The trial is 2 machine-hours or 7 days | Needed after the trial | Yes |
| Koyeb | Not on free | No free compute plan for new accounts | n/a | n/a |
| Hugging Face Spaces | **No**: the disk is wiped on restart, and saving data needs a storage add-on | Built for AI demos | n/a | n/a |

**Pick: PythonAnywhere.** It's the only option that is free, has no card,
doesn't sleep, *and* keeps your SQLite file. That last point matters most: on
Render your recipes would vanish every time the app restarted.

The two catches, and how to live with them:

1. **"Import from a link" will usually fail on the hosted copy.** Free accounts
   can only reach an allow-list of websites. The app then shows its normal
   "couldn't get that page" message. **Pasting JSON (option A on the Import
   page) works fine**, and so does importing links on your computer copy.
2. **The app switches off after 1 month** unless you press
   **"Run until 1 month from today"** on the Web tab (step 9). Set a monthly
   reminder on your phone. Your recipes aren't deleted when it switches off.
   Pressing the button brings the app back.

Sources: [PythonAnywhere free features](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/),
[PythonAnywhere pricing](https://www.pythonanywhere.com/pricing/),
[PythonAnywhere: free account changes](https://blog.pythonanywhere.com/221/),
[Render free plan](https://render.com/docs/free),
[Railway free trial](https://docs.railway.com/reference/pricing/free-trial),
[Railway plans](https://docs.railway.com/reference/pricing/plans),
[Fly.io free trial](https://fly.io/docs/about/free-trial/),
[Fly.io pricing](https://fly.io/docs/about/pricing/),
[Koyeb pricing](https://www.koyeb.com/pricing),
[Hugging Face Spaces storage](https://huggingface.co/docs/hub/spaces-storage).

---

## What's in the code for this (already done)

- **Password gate:** when the `APP_PASSWORD` setting exists, every page asks for
  the password first. You stay logged in on your phone for 30 days. On your
  computer (`python app.py`) there's no password, same as before.
- **Download all recipes:** Import page → "Back up your recipes" (or go to `/export`).
- **`wsgi.py`**: the file the server starts the app from. It never turns on debug mode.
- **`.env.example`**: a template for the secret settings file that lives *only*
  on the server. Your GitHub repo is **public**, so the password must never go in it.

---

## Step 1: Create the account

1. Go to **https://www.pythonanywhere.com** and click **Pricing & signup** (top right).
2. Under **Beginner** (the free one), click **Create a Beginner account**.
3. Fill in **Username** (this becomes your web address, e.g. `nicsrecipes` gives
   `nicsrecipes.pythonanywhere.com`), **Email**, and **Password**. Tick the terms box
   and click **Register**.
4. Open the confirmation email and click the link in it.
5. If a "tour" pops up, you can click **End tour**.

## Step 2: Copy your code onto the server

The server copies your code straight from GitHub. Because the repo is public,
it doesn't need a GitHub login.

1. At the top of the PythonAnywhere page, click **Consoles**.
2. Under **Start a new console**, click **Bash**. A black terminal window opens.
3. Type these lines one at a time, pressing Enter after each. The second-to-last
   one takes a minute or two.

   ```bash
   git clone https://github.com/nicolassimi2104/recipe-app.git
   cd recipe-app
   mkvirtualenv --python=/usr/bin/python3.13 recipe-venv
   pip install -r requirements.txt
   ```

   After `mkvirtualenv`, the start of the line changes to `(recipe-venv)`.
   That's the server's version of your `venv` folder.

## Step 3: Make a good SECRET_KEY

`SECRET_KEY` is a long random string the app uses to sign your login cookie, so
nobody can fake being logged in. You never type it anywhere except the settings file.

In the same Bash console, type:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

It prints 64 random letters and numbers. Select them with your mouse and copy
(**Ctrl+C** may not work in the console; use right-click → **Copy**). Leave the console open.

## Step 4: Write the settings file (.env)

1. Click **Files** at the top of the page.
2. Click the **recipe-app/** folder on the left.
3. In the box under **Files** that says "Enter new file name", type `.env` and
   click **New file**. An editor opens.
4. Paste this in, and replace the two placeholder values:

   ```
   APP_PASSWORD=pick-a-long-password-you-can-type-on-your-phone
   SECRET_KEY=paste-the-64-characters-from-step-3
   SESSION_COOKIE_SECURE=1
   ```

   - Don't put spaces around `=` and don't add quotes.
   - Make the password long, e.g. 4 random words: `purple-tractor-lemon-cloud`.
     Nothing limits how many guesses someone can make, so length is your protection.
   - Don't use a password you use anywhere else.
5. Click **Save** (top right of the editor).

This file stays on the server only. `.gitignore` stops it from ever going to GitHub.

## Step 5: Create the web app

1. Click **Web** at the top of the page.
2. Click **Add a new web app**, then **Next** (it shows your free address).
3. Choose **Manual configuration**. **Don't** pick "Flask": that option makes
   a new empty app instead of using yours.
4. Choose **Python 3.13**, then click **Next**.

You're now on your web app's settings page. Scroll down and fill in these sections:

**Code:**
- Click the value next to **Source code**, type `/home/YOURNAME/recipe-app`, and press the ✓ tick.
- Do the same for **Working directory**: `/home/YOURNAME/recipe-app`.

**Virtualenv:**
- Click **Enter path to a virtualenv**, type `recipe-venv`, and press the ✓ tick.
  It fills in the full path for you.

**Static files** (makes the page styling load faster):
- Click **Enter URL** and type `/static/`. Then click **Enter path** and type
  `/home/YOURNAME/recipe-app/static`.

**Security:**
- Switch **Force HTTPS** to **Enabled**.

## Step 6: Point the server at the app (WSGI file)

1. In the **Code** section, click the link next to **WSGI configuration file**
   (it looks like `/var/www/YOURNAME_pythonanywhere_com_wsgi.py`).
2. An editor opens with lots of example text. **Select all of it (Ctrl+A) and delete it.**
3. Paste in exactly this, replacing YOURNAME:

   ```python
   import sys

   path = "/home/YOURNAME/recipe-app"
   if path not in sys.path:
       sys.path.insert(0, path)

   # wsgi.py reads the .env settings file and builds the app
   from wsgi import app as application
   ```

4. Click **Save**.

## Step 7: First start

1. Go back to the **Web** tab and click the big green **Reload YOURNAME.pythonanywhere.com** button.
2. Click the link at the top of the page (`YOURNAME.pythonanywhere.com`).
3. You should see the **Log in** page. Type your `APP_PASSWORD` and you'll see the 4 starter recipes.

**If you see "Something went wrong" instead:** on the **Web** tab, scroll to
**Log files** and click the **error log**. Read the bottom few lines. The most
common causes:
- `APP_PASSWORD is set, so SECRET_KEY must be set too`: fix the `.env` file (step 4).
- `No module named 'wsgi'`: the path in the WSGI file (step 6) has a typo.
- `No module named 'flask'`: the virtualenv path (step 5) isn't set.

After any fix, click **Reload** again.

## Step 8: Move your recipes from your computer

Do this on your computer, not your phone, because it's easier to copy a big block of text there.

1. On your computer, start the app as usual (`python app.py`) and open http://localhost:5000.
2. Click **Import**, scroll to **Back up your recipes**, and click **Download all recipes**.
   A file like `recipes-2026-10-16.json` lands in your **Downloads** folder.
3. In File Explorer, right-click that file → **Open with** → **Notepad**.
   Press **Ctrl+A** then **Ctrl+C** to copy all of it.
4. In your browser, go to `https://YOURNAME.pythonanywhere.com`, log in, and click **Import**.
5. Click in box **A. Paste JSON**, press **Ctrl+V**, then click **Preview**.
6. The 4 starter recipes are already on the server, so they show as "already
   exists" and get skipped. That's expected. Click **Save … recipes**.

Use the same **Download all recipes** button on the hosted copy now and then as
a backup. Do it before big changes too.

## Step 9: Keep it switched on (every month)

Free apps switch off after 1 month. To keep yours running:

1. Log in to pythonanywhere.com and click **Web**.
2. Click **Run until 1 month from today**.

Set a monthly repeating reminder on your phone. PythonAnywhere also emails you
before it expires. If you miss it, your recipes are still safe. Click the same
button and then **Reload** to bring the app back.

## Step 10: Open it on your phone and add it to your home screen

Open `https://YOURNAME.pythonanywhere.com` in your phone's browser and log in.
You stay logged in for 30 days.

**iPhone (Safari):**
1. Tap the **Share** button (the square with an arrow pointing up, at the bottom of the screen).
2. Scroll down and tap **Add to Home Screen**.
3. Change the name if you like (e.g. "Recipes") and tap **Add**.

**Android (Chrome):**
1. Tap the **⋮** menu (three dots, top right).
2. Tap **Add to Home screen** (on some phones it's **Add to home screen → Install** or **Create shortcut**).
3. Tap **Add**.

The icon now opens the app straight away.

---

## Later: updating the hosted copy after new features

When a new feature is merged on GitHub:

1. On PythonAnywhere, click **Consoles** and open your **Bash** console (or start a new one).
2. Type:

   ```bash
   cd ~/recipe-app
   git pull
   workon recipe-venv
   pip install -r requirements.txt
   ```

3. Click **Web**, then the green **Reload** button.

Your recipes aren't touched. `recipes.db` and `.env` aren't part of git, so
`git pull` never overwrites them.

## Changing the password

Edit `.env` (**Files** → **recipe-app** → click `.env`), change `APP_PASSWORD`,
**Save**, then **Reload** on the Web tab. To also log out every device that's
currently logged in, make a new `SECRET_KEY` too (step 3).

## For reference: other hosts

`gunicorn` is in requirements.txt, so on hosts that run a start command (like
Render or Railway) the command is `gunicorn wsgi:app`. Set `APP_PASSWORD`,
`SECRET_KEY` and `SESSION_COOKIE_SECURE=1` as environment variables in that
host's dashboard. If the host has a persistent disk, set `DB_PATH` to a file on that disk.
