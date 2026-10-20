# Putting the Recipe App on Render (free)

This is the second way to put the app online. The first is PythonAnywhere,
in [DEPLOY.md](DEPLOY.md). Pick one; you don't need both.

## What to know first

- **It falls asleep.** After 15 minutes with no visitors, Render's free app
  switches off. The next visit wakes it up, which takes about a minute.
- **Files get wiped.** Every restart, sleep or update wipes the app's files,
  so the usual `recipes.db` would be lost. To keep your recipes, the app saves
  a copy of the whole database into a free **Postgres** database after every
  change, and copies it back when it wakes up. You don't have to do anything
  for this.
- **The free Postgres expires after 30 days.** After that you get a 14-day
  grace period, and then it's deleted. It has **no backups**. So:
  1. Download a backup now and then: **Import** page → **Download all recipes**.
  2. When the database expires, make a new one ("Every month or so" below).
     The app then reloads your recipes from the backup file you uploaded (step 5).
- **What the backup file doesn't keep:** favorites (stars), this week's plan
  and Fresh finds. Recipes, tags, photos and links come back. Labels like
  protein are guessed again.
- "Import from a link" works on Render. It mostly doesn't on PythonAnywhere.

## Setup (about 15 minutes)

1. **Make an account** at https://render.com. Signing in with GitHub is
   easiest. Free accounts don't need a credit card.
2. **Download a backup** from your computer copy of the app: open it, go to
   **Import**, and click **Download all recipes**. You get a file like
   `recipes-2026-10-20.json`.
3. In Render, click **New +** → **Blueprint**, and pick the `recipe-app` repo.
   Render reads `render.yaml` and shows two things to create: **recipe-app**
   (the website) and **recipe-db** (the database).
4. It asks for **APP_PASSWORD**. Type the password you want for the app
   (this is what you'll type on your phone). Click **Apply**. The first
   build takes a few minutes. **Don't add or change anything in the app
   yet**: until step 5 it only has the sample recipes, and your first change
   would save those as your recipes (then the backup wouldn't load).
5. **Upload your backup so your recipes come along:**
   - Open **recipe-app** → **Environment** → **Secret Files** → **Add Secret File**.
   - File name: `recipes-backup.json`
   - Contents: open the file from step 2 in Notepad, copy everything, and paste it.
   - Save. The app restarts, finds the empty database, and loads your recipes.
     (If it doesn't restart by itself, click **Manual Deploy** → **Deploy latest commit**.)
   - (Without this file, a new app starts with the 4 sample recipes.)
6. **Open the app:** the link is at the top of the **recipe-app** page,
   like `https://recipe-app-xxxx.onrender.com`. Log in with your password, and
   add it to your phone's home screen.

## Every month or so

- **Update the backup:** on the hosted app, go to **Import** → **Download all
  recipes**, then replace the Secret File's contents with the new file. That
  way a new database starts from recent recipes.
- **When Render emails that the database is expiring:** download a fresh
  backup, update the Secret File, then delete **recipe-db** and create a new
  free Postgres called `recipe-db`. Then, in **recipe-app** → **Environment**,
  set `DATABASE_URL` to the new database's **Internal Database URL** and save.
  The app restarts and reloads your recipes from the backup.

## If something goes wrong

- **"Recipes restored from: ..."** in the app's **Logs** says what happened
  at startup: `saved copy` (normal), `backup file` (reloaded from your JSON),
  or `nothing` (brand-new app, sample recipes).
- **The app won't start and the log says it can't connect to Postgres:**
  the app refuses to start without its saved copy on purpose. If it started
  empty, the next change would save over your recipes. Check that
  **recipe-db** is running and `DATABASE_URL` is right.
- **"The backup file ... can't be read":** the Secret File isn't valid JSON.
  Paste the exported file again, all of it.
