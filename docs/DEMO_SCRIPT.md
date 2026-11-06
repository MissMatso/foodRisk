# FoodRisk final demonstration script

NPRJ740 presentation and system demonstration (10 marks). Written for the 2 November 2026 build: 283 automated tests, model `simulated_rf_v2`.

The rubric awards marks for five things: a clear overview (1), one end-to-end workflow (2), **lecturer-selected functionality and a failure condition (4)**, explaining engineering decisions (1) and answering questions (2). Most of the marks are in the lecturer’s hands, so this script has a fixed main workflow and a ready answer for every requirement the lecturer might pick.

## 1. Before you walk in

Do these 30 minutes early, and reseed on the day. The password-guessing warning on the admin report only shows failures from the last 24 hours, so a database seeded yesterday will not show it.

1. Open the project folder, activate the virtual environment, and check `.env` has `DEBUG=True`. With `DEBUG=False` the model registry refuses the research model and scoring will fail.
2. Run these commands:

```
python manage.py migrate
python manage.py seed_demo_data --reset
python manage.py runserver
```

3. Open **three private browser windows** at http://127.0.0.1:8000/ and sign in as a different role in each, so you never have to log out mid-demo. (An admin lands on the system report; staff and analysts land on the dashboard.)
4. Keep a second terminal open in the project folder, ready for `python manage.py test`.
5. Have the report open at section 4 (requirements) and section 7.2 (test table), and `docs/diagrams/` ready.
6. Do the first score once before the demo. The first score loads the model (about one second); later ones are fast.

| Role | Username | Password |
|---|---|---|
| System Admin | `admin_demo` | `DemoPass123!` |
| NGO Staff | `staff_demo` | `DemoPass123!` |
| Data Analyst | `analyst_demo` | `DemoPass123!` |

The seed gives you about 255 households (5 handwritten, 250 generated from held-out test rows) with six months of history. Roughly 138 are currently Low, 14 Medium and 103 High, so numbers may differ slightly on your machine. **Dlamini Household** (ZF Mgcawu, score about 76) is the ready-made High example.

## 2. The main workflow (about 6 minutes)

Open with one sentence: *FoodRisk helps a Northern Cape NGO register households, estimate food-insecurity risk, record follow-up actions and review results, with three roles that each see different things.* Then say the honest limit before anyone asks: *the model is trained on simulated data, so its scores show the workflow works, not that it predicts real hunger.*

**Step 1. Public pages (30 seconds).** Show `/`, `/how-it-works/` and `/model/`. Point at the limitations page.

**Step 2. Staff registers a household (1 minute).** In the staff window open **Households**, search for the name first (nothing found), then click **+ Register Household** and enter:

| Field | Value |
|---|---|
| Name | Demo Household |
| Address / contact | 9 Test Rd / 0711112222 |
| Ward / village / province | Hantam / Calvinia / Northern Cape |
| Monthly income | 900 |
| Household size / dependents | 6 / 3 |
| Children under 5 / elderly | 2 / 1 |
| Employment | Unemployed |
| Distance to market (km) | 30 |
| Water access | River |

Click **Save Household**. Say: *validation runs before anything is saved.*

**Step 3. Score and explain (1 minute).** On the household page click **Generate Risk Score**. Expect about **97, High**. Click **Explain this score**. The top drivers should be income per capita, employment status and monthly income. Say: *the explanation is computed on request from the household’s original inputs, which are stored encrypted.* Open **View Full History** to show the assessment is saved as its own record.

**Step 4. Record an action (45 seconds).** Click **Record action**, choose an action, add a note and a follow-up date, then **Save intervention**. Later use **Update / complete** to close it.

**Step 5. Dashboard (30 seconds).** Open **Dashboard**. Households are ordered by latest score. Use **Filter** for High.

**Step 6. Analyst view (1 minute).** In the analyst window open Reports. Show **Response coverage** ("24 high-risk households have no action yet; John Taolo Gaetsewe has the most"), then filter by ward **Hantam**, show **Risk by group** (sort a column), then in **Download** tick Household, Score and Category, choose *Latest assessment per household* and download the CSV. Show the **model-wide SHAP** table and say it is measured on the 2,000 held-out simulated test records, not real households. Scroll to **Model performance** and say the limits: *accuracy and the confusion matrix measure agreement with simulated labels, and the card says the model is not externally validated.*

**Optional, 30 seconds: a new account.** In the admin window open **Users**, register a user (no password to type: the system shows a one-time password with the username), then sign in as them in a private window (Ctrl + Shift + N). The same window would share the admin's sign-in; the sign-in page now says so. They are taken straight to *Change password*. The demonstration accounts are deliberately not flagged, so only accounts you create this way are interrupted.

**Step 7. Admin view (1 minute).** In the admin window open **System report**. Show the sign-in summary and the password-guessing warning, then open **Users** (the one place accounts are changed) and change a role. Open **Audit Log**: filter household changes by *Updated*, then the **Sign-ins and account changes** tab to show the role change.

## 3. If the lecturer picks a requirement

Find it here and do exactly this. Every row has been dry-run against the live build.

| Requirement | Do this | Expect |
|---|---|---|
| FR001, BR-02 | Analyst window: open `/households/new/`. Guest window: open `/dashboard/`. | Analyst gets 403 Forbidden. Guest is sent to sign-in. |
| FR002–FR004, BR-01 | Register a household; then try income `-5`. | Saved with created/updated times. Error: *Income must be ≥ 0.* |
| FR005, FR007, FR008 | Generate a score, open **View Full History**. | Score within 5 seconds; saved with category, time, model version. |
| FR006 | Show the bands on `/how-it-works/`. Run `python manage.py test dashboard.test_rules`. | Low 0–33, Medium 34–66, High 67–100; edge values pass. |
| FR009, BR-05 | Dashboard, then **Filter**. | Sorted by latest score for the configured model only. |
| FR010, BR-06 | Edit a household’s income, open **Full Audit Log**. | Entry names the *field* changed, never the old or new value. |
| FR011, FR018 | Analyst: filter by ward and dates, then download CSV and PDF. | Downloads match the filter; a bad date gives an error. |
| FR012, FR013 | **Record action**, then **Update / complete**. | Status moves open to completed. Analyst cannot create one. |
| FR014 | Admin: **Users**, deactivate `staff_demo3`. | Done; your own row has no controls. |
| FR015, BR-07 | Admin: System report, PDF and CSV. Staff window: open the same URL. | Totals agree across page and downloads; staff get 403. |
| FR016, BR-08 | Admin: change a role on **Users**. | Event listed on the Audit Log account tab and the system report with old and new role. |
| FR017, BR-09 | Private window: 5 wrong passwords for `staff_demo2`, refresh the system report. | Warning names `staff_demo2`. Downloads hold counts but no addresses. |
| FR019 | Analyst: **Model performance**. | Matches the model’s recorded results, with a limitations note. |
| FR020, BR-10 | Staff: register the same household (name, ward, village, phone) twice. | Second is refused: *This household is already registered (record N…)*. |
| FR024 | Staff: register a new name using an existing household’s phone number. | Warning *Match: same phone number*, with a link and no private details. Tick to confirm. |
| FR027 | Staff: register a new name and phone at an existing address written differently (`12 Church St, Galeshewe, Kimberley` and `12 church st galeshewe kimberley`). | Refused until a reason is given (*Reason for sharing an address*); with *backyard room 2* it saves and the reason shows on the household page. |
| FR028 | Admin: **Audit Log**, filter by user and date, click Next. | Filters kept on every page; CSV holds the same rows. |
| FR029 | Analyst: Dashboard, click **Ward** then **Ward** again; Reports, **Download** with chosen columns. | A–Z then Z–A; file has exactly the ticked columns. |
| FR021–FR023, BR-14 | Admin: **Users**, **Reset password** for `staff_demo3`; note the temporary password; sign in as that user. | Sent to *Change password*; the temporary password is refused as the new one; after a valid change the system opens. |
| FR025 | Staff: register with ward `hantam ` (trailing space, lower case). | Stored as `Hantam`; the ward and village fields suggest existing places. |
| FR026 | Staff: edit a household’s income, then open **Dashboard**. | *Out of date* badge until a new score is generated. |
| BR-15 | Analyst: open any household. | *Address and contact: not shown to analysts*. |
| BR-12 | Admin: **Audit Log**, open a household, **Delete household**, confirm. Staff: open `/households/<id>/delete/`. | Confirmation lists what is removed; after deleting, the audit log shows the entry with the admin's name. Staff get 403. |
| NFR005 | Run the command below. | Contact is unreadable ciphertext. |
| NFR002 | Browser developer tools, Network tab, click **Generate Risk Score**. | Under 5 seconds. |

For NFR005, run this and point at the output:

```
python manage.py shell -c "from django.db import connection; c=connection.cursor(); c.execute('select contact from households_household limit 1'); print(c.fetchone())"
```

## 4. Failure conditions to show on request

The lecturer may ask for a validation, access-control, alternative-flow, boundary or error case. These are ready:

| Kind | How | Expected result |
|---|---|---|
| Validation | Income `-5` | *Income must be ≥ 0.* |
| Validation | Dependents `9` with size `6` | *Dependents cannot exceed household size.* |
| Validation | Household size `0` | *Household size must be > 0.* |
| Validation | Dependents `1` with 2 children and 1 elderly | *Dependents must include children and elderly members.* |
| Access control | Analyst opens `/households/new/` | 403 Forbidden |
| Access control | Staff opens `/dashboard/reports/risk/` or `/dashboard/reports/system/` | 403 Forbidden |
| Access control | Admin cannot edit their own role | No controls on own row |
| Access control | Sign in as a user whose password was issued by an admin and open the dashboard | Redirected to *Change password* |
| Validation | Contact `n/a`, or income `99999999` | *Enter a valid South African phone number…* / *…looks like a typing error* |
| Duplicate | Register the identical household twice; or the same phone number under a new name | Refused; or warning with a confirmation box |
| Duplicate | Four relatives apply separately from one address | First saved; the rest refused at the address until a reason is given |
| Database rule | `python manage.py test households.tests.test_shared_address` | Database refuses size 0 and dependents above size even when `clean()` is skipped |
| Alternative flow | Double-click **Generate Risk Score** | One score and *no duplicate was created* |
| Alternative flow | Analyst filters with date `oops` in the address bar | HTTP 400, no data shown |
| Alternative flow | Deactivate a user, then try to sign in as them | Sign-in fails and appears as a failed login |
| Boundary | `python manage.py test dashboard.test_rules` | 33 is Low, 34 Medium, 66 Medium, 67 High |
| Error | `python manage.py test households predictions` | Missing-model and inference-failure tests pass: no prediction saved, clear message |

Do not break the model live. Show model failures through the automated tests above, not by changing settings during the demo.

**Show the tests on request:**

```
python manage.py test            # all 283
python manage.py test accounts   # roles, role changes, login tracking
python manage.py test dashboard  # reports, filters, model card, seed, rules
```

## 5. If something goes wrong

| Problem | Fix |
|---|---|
| Score fails with an error | `DEBUG` is `False` in `.env`. Set it to `True` and restart. |
| Reports look empty or the warning is missing | `python manage.py seed_demo_data --reset`, then restart. |
| First score is slow | Normal. The model loads once. Say so. |
| Port already in use | `python manage.py runserver 8001` and use that port. |
| Cannot sign in | Check you typed `DemoPass123!` and the username exactly. |

## 6. Engineering decisions and likely questions

Answer in one or two sentences. Say plainly what you do not know.

**Why Django with server-rendered pages?** One application shares models, sessions and permissions between the pages and the API, so setup is simpler for a local prototype. The cost is that web and API permissions both have to be checked, and the tests do that.

**Why a random forest?** It handles mixed inputs and gives a score with an explanation. Honestly, a simpler logistic regression scores almost the same, because the training labels were generated from simple rules. The Model performance card shows the comparison.

**Is the model accurate?** It agrees with the simulated labels, which is all it can show. It has not been validated on real households and its probabilities are not calibrated. It must not be used to allocate real aid.

**Why simulated data, and what about real data?** *[Say in your own words what did not align in the real-data attempt, and that the real-data requirement remains outstanding.]* The registry keeps the earlier real-data artefacts, and the system does not hide the gap.

**Why are explanations on request?** SHAP is slow and only needed when someone questions a score, so it is computed once from the saved original inputs and cached.

**Why signals for the audit log?** Signals also capture changes made through the API and the Django admin, not just the web forms. The audit stores field names, not values, so it does not copy personal data.

**Why a separate sign-in event log?** It keeps the household audit meaning intact and records sign-ins however they happen. A failed login for an unknown username stores nothing, because people sometimes type a password into that box.

**What happens after five failed logins?** An administrator sees a warning. There is no automatic lockout, and that is listed as a known limitation (KI-05). It would be the next feature.

**What about privacy?** Contact, address, income and health flags are encrypted; name, ward and village stay readable, which is a listed limitation (KI-04). A retention and protection policy is still needed.

**What would you do next?** Train and validate on real field data with the NGO, calibrate the scores, add lockout and longer event retention, deploy behind TLS, and run the browser and usability checks that are still open.

## 7. Quick reference

| Page | URL |
|---|---|
| Landing, how it works, model | `/`, `/how-it-works/`, `/model/` |
| Sign in | `/accounts/login/` |
| Register household | `/households/new/` |
| Dashboard | `/dashboard/` |
| Reports (role-based) | `/dashboard/reports/` |
| Analyst risk report | `/dashboard/reports/risk/` |
| Admin system report | `/dashboard/reports/system/` |
| Audit log | `/households/audit-log/` |
| Users | `/accounts/users/` |

**Open items to be honest about if asked:** submission details are still to be added, current screenshots, Firefox and Safari checks, a timed usability test, and the real-data requirement. The benchmark was recorded before the account event log was added and has not been rerun.
