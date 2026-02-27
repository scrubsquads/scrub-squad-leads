"""
Close CRM — Rewrite All Email Templates + Create New Ones
Deletes stale templates, rewrites active ones, creates Under Contract & In-House templates.
"""
import json
import time
import urllib.request
import urllib.error
import base64
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.environ.get("CLOSE_API_KEY", "")
BASE_URL = "https://api.close.com/api/v1"
AUTH = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()


def api_put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method="PUT",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        time.sleep(0.5)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ERROR {e.code}: {err[:400]}")
        raise


def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", data=body, method="POST",
        headers={"Authorization": AUTH, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        time.sleep(0.5)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ERROR {e.code}: {err[:400]}")
        raise


def api_delete(path):
    req = urllib.request.Request(
        f"{BASE_URL}/{path}", method="DELETE",
        headers={"Authorization": AUTH}
    )
    urllib.request.urlopen(req)
    time.sleep(0.3)


# =====================================================================
# Sign-off blocks (HTML)
# =====================================================================
SIG_CHRISTIAN = (
    "Christian<br>"
    "Account Manager | Scrub Squads<br>"
    "786-838-4148"
)
SIG_SENTEL = (
    "Sentel Mays<br>"
    "General Manager | Scrub Squads<br>"
    "786-838-4148"
)


def main():
    if not API_KEY:
        print("ERROR: CLOSE_API_KEY not set")
        sys.exit(1)

    # =================================================================
    # STEP 1: Delete 4 stale templates
    # =================================================================
    print("=" * 60)
    print("STEP 1: Deleting stale templates")
    print("=" * 60)
    stale = [
        ("tmpl_M48Spux37hrbJ2BePMy85eC3ihFIKBzDTnXhEiGZ9qS", "December"),
        ("tmpl_uSExs7e2nT1ItuNKR64fEivThclWTC526jLLronpiNF", "New Year's Eve"),
        ("tmpl_3xASorJLaMzOzTz70BtSmH1nGpocQtwSqjBwl1CXEO8", "Vending Machines"),
        ("tmpl_vNCVnBNb9JaUXL1zKddruuP8HnNCnoHgC8gguKlbie9", "#9 Placeholder"),
    ]
    for tid, name in stale:
        try:
            api_delete(f"email_template/{tid}/")
            print(f"  Deleted: {name}")
        except Exception:
            print(f"  Already deleted or not found: {name}")

    # =================================================================
    # STEP 2: Rewrite active templates
    # =================================================================
    print("\n" + "=" * 60)
    print("STEP 2: Rewriting active templates")
    print("=" * 60)

    # -----------------------------------------------------------------
    # Commercial Sequence Step 1 (tmpl_xNwon8zcmW0R7WXZ2eVbfBHnRG4MsI6vfwbIeE9ICzH)
    # -----------------------------------------------------------------
    print("\n  Rewriting: Commercial Step 1...")
    api_put("email_template/tmpl_xNwon8zcmW0R7WXZ2eVbfBHnRG4MsI6vfwbIeE9ICzH/", {
        "name": "Commercial | Step 1 - Introduction",
        "subject": '{{ lead.name }} | Quick Introduction from Scrub Squads',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "We're a South Florida cleaning company that works with offices, property managers, "
            "medical facilities, and construction sites across Miami-Dade and Broward.<br><br>"
            "Our clients stick with us because we actually show up, communicate clearly, "
            "and don't cut corners. Simple stuff that's surprisingly hard to find.<br><br>"
            "If you ever need a second option for cleaning services, I'd be happy to chat. "
            "No pitch, no pressure — just an introduction.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Commercial Sequence Step 2 (tmpl_UAPYU33oucmZiJOMtqA9oTOXvKHnISy8GPeF7KzeZog)
    # -----------------------------------------------------------------
    print("  Rewriting: Commercial Step 2...")
    api_put("email_template/tmpl_UAPYU33oucmZiJOMtqA9oTOXvKHnISy8GPeF7KzeZog/", {
        "name": "Commercial | Step 2 - Why Scrub Squads",
        "subject": '{{ lead.name }} | Why South Florida Property Managers Trust Us',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "When we started Scrub Squads, we built it around the complaints we kept hearing "
            "from facility managers:<br><br>"
            "- Cleaners don't show up on schedule<br>"
            "- Quality drops after the first month<br>"
            "- Nobody answers when there's a problem<br><br>"
            "So we fixed those things. Every client gets a dedicated cleaning schedule, "
            "regular quality checks, and a direct line to our team — not a call center.<br><br>"
            "One property manager in Doral told us their tenant complaints about cleanliness "
            "dropped by 40% in the first three months after switching to us.<br><br>"
            "Would it make sense to have a quick conversation about your current setup?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Commercial Sequence Step 3 (tmpl_Ct6FrMxPykqKRDvz8BXScv06VxBfcOaBKmaiPyo4nac)
    # -----------------------------------------------------------------
    print("  Rewriting: Commercial Step 3...")
    api_put("email_template/tmpl_Ct6FrMxPykqKRDvz8BXScv06VxBfcOaBKmaiPyo4nac/", {
        "name": "Commercial | Step 3 - Common Frustrations",
        "subject": '{{ lead.name }} | Sound Familiar?',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "These are the three things we hear most from facility managers "
            "before they switch providers:<br><br>"
            "1. \"My cleaning crew is inconsistent — some nights they don't show up at all.\"<br>"
            "2. \"I'm spending too much time managing the cleaning instead of my actual job.\"<br>"
            "3. \"The quality is fine for a week, then it drops off.\"<br><br>"
            "If any of that sounds familiar, we should talk. We built our entire operation "
            "around solving these exact problems.<br><br>"
            "Would a 10-minute call this week work?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Commercial Sequence Step 4 (tmpl_hI5g7Ib4gQrZabd3N526JocpWhOvwYLwNzK50Oi1DLE)
    # -----------------------------------------------------------------
    print("  Rewriting: Commercial Step 4...")
    api_put("email_template/tmpl_hI5g7Ib4gQrZabd3N526JocpWhOvwYLwNzK50Oi1DLE/", {
        "name": "Commercial | Step 4 - Free Walkthrough",
        "subject": '{{ lead.name }} | Free Walkthrough + Custom Quote',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "We're offering complimentary walkthroughs for South Florida businesses "
            "this month. Here's what we cover:<br><br>"
            "- Walk your space and identify cleaning priorities<br>"
            "- Spot cost-saving opportunities (frequency, bundled services)<br>"
            "- Deliver a custom cleaning proposal within 24 hours<br><br>"
            "It takes about 15 minutes, there's zero obligation, and you'll walk away "
            "with a clear picture of what professional cleaning would look like for "
            "your property — whether you go with us or not.<br><br>"
            "Want me to set one up?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Commercial Sequence Step 5 (tmpl_KkZxpp7JLLO3BZTDqA041BZ6ZnRLKNmY3j5eslJRhCB)
    # -----------------------------------------------------------------
    print("  Rewriting: Commercial Step 5...")
    api_put("email_template/tmpl_KkZxpp7JLLO3BZTDqA041BZ6ZnRLKNmY3j5eslJRhCB/", {
        "name": "Commercial | Step 5 - Cost Saving Tips",
        "subject": '{{ lead.name }} | 3 Ways to Cut Cleaning Costs',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Quick value-add before I go quiet — here are 3 ways South Florida "
            "businesses save on cleaning without sacrificing quality:<br><br>"
            "<b>1. Optimize frequency.</b> Not every space needs daily service. "
            "A tailored schedule can cut costs 20-30%.<br>"
            "<b>2. Bundle services.</b> Combining janitorial, floor care, and "
            "post-construction cleaning with one provider eliminates markups.<br>"
            "<b>3. Use eco-friendly products.</b> Lower supply costs, better air quality, "
            "and fewer sick days for your team.<br><br>"
            "We help our clients do all three. If you'd like, I can run a free cost "
            "comparison for your property — no strings attached.<br><br>"
            "Just reply \"yes\" and I'll put it together.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Education Step 1 (tmpl_alUW1vACRTZXlHUTkHo4Wlkm5MyjNac58XXLv8sqHc8)
    # -----------------------------------------------------------------
    print("\n  Rewriting: Education Step 1...")
    api_put("email_template/tmpl_alUW1vACRTZXlHUTkHo4Wlkm5MyjNac58XXLv8sqHc8/", {
        "name": "Education | Step 1 - Safe Classrooms",
        "subject": '{{ lead.name }} | Keeping Your Classrooms Safe and Clean',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Students and staff deserve a clean, safe environment — and your team "
            "shouldn't have to worry about whether the cleaning crew actually showed up.<br><br>"
            "Scrub Squads works with schools and educational facilities across South Florida "
            "to maintain spotless, sanitized spaces without disrupting class time. We offer:<br><br>"
            "- Nightly janitorial and restroom sanitation<br>"
            "- Floor care and deep cleaning<br>"
            "- Emergency cleaning and day porter options<br><br>"
            "Every member of our staff is background-checked, insured, and trained "
            "specifically for educational environments.<br><br>"
            "Would you be open to a 15-minute walkthrough this week?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Education Step 2 (tmpl_uNgpRMOCUCGOc8dRZJNIl6pGX9MRHnDjA43FtUByfv4)
    # -----------------------------------------------------------------
    print("  Rewriting: Education Step 2...")
    api_put("email_template/tmpl_uNgpRMOCUCGOc8dRZJNIl6pGX9MRHnDjA43FtUByfv4/", {
        "name": "Education | Step 2 - Budget Friendly",
        "subject": '{{ lead.name }} | Flexible Cleaning Plans for Schools',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Following up — I know budget is always a factor for schools, "
            "so I wanted to share how we typically work with educational facilities:<br><br>"
            "- <b>Flexible scheduling</b> — we work around school hours, events, and breaks<br>"
            "- <b>Scalable plans</b> — start with common areas and expand as budget allows<br>"
            "- <b>No long-term lock-in</b> — month-to-month options available<br><br>"
            "We currently serve schools in the Miami-Dade area and understand the "
            "specific requirements for educational environments (health codes, "
            "child safety protocols, etc.).<br><br>"
            "Would it help to see a sample cleaning plan for a facility similar to yours?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Education Step 3 / Pricing (tmpl_vT4HPppOE4E8JmsZUdgqYYu8S3sYmjeSTsAd1wk3TwI)
    # -----------------------------------------------------------------
    print("  Rewriting: Education Step 3 (Pricing)...")
    api_put("email_template/tmpl_vT4HPppOE4E8JmsZUdgqYYu8S3sYmjeSTsAd1wk3TwI/", {
        "name": "Education | Step 3 - Pricing Context",
        "subject": '{{ lead.name }} | What School Cleaning Typically Costs in South Florida',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Last email from me — wanted to leave you with something useful.<br><br>"
            "General cleaning rates for South Florida schools typically range from "
            "$0.10 to $0.28 per square foot, depending on the scope, frequency, "
            "and location:<br><br>"
            "- Miami: $0.12 - $0.25/sqft<br>"
            "- Doral: $0.10 - $0.22/sqft<br>"
            "- Coral Gables: $0.14 - $0.28/sqft<br>"
            "- Homestead: $0.10 - $0.20/sqft<br><br>"
            "These are ballpark numbers — final pricing always depends on your specific "
            "space and needs. But it gives you a starting point for budgeting.<br><br>"
            "If you'd like an exact quote, I'm happy to spend 15 minutes walking your "
            "facility and putting together a custom proposal.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Re-Engagement Step 1 (tmpl_c8KXaWQqWqArVVJK3Vwy9ZDU22sm16aNoOJbOiJzQrH)
    # FULL REWRITE - drop "I noticed you opened" angle
    # -----------------------------------------------------------------
    print("\n  Rewriting: Re-Engagement Step 1 (full rewrite)...")
    api_put("email_template/tmpl_c8KXaWQqWqArVVJK3Vwy9ZDU22sm16aNoOJbOiJzQrH/", {
        "name": "Re-Engagement | Step 1 - Fresh Start",
        "subject": '{{ lead.name }} | Still Looking for a Reliable Cleaning Partner?',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "I reached out a while back about cleaning services for {{ lead.name }} "
            "and wanted to circle back.<br><br>"
            "Since then, we've expanded our team and taken on several new commercial "
            "properties in your area. If you were on the fence before, now might be "
            "a good time to revisit the conversation.<br><br>"
            "We're currently offering free walkthroughs with a custom proposal "
            "delivered within 24 hours — no obligation, no pressure.<br><br>"
            "Worth a quick chat?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Re-Engagement Step 2 (tmpl_Y9SIB9NhsKxzjYCE0gNinmW1REnOz6YkmJeIO6lY1CM)
    # -----------------------------------------------------------------
    print("  Rewriting: Re-Engagement Step 2...")
    api_put("email_template/tmpl_Y9SIB9NhsKxzjYCE0gNinmW1REnOz6YkmJeIO6lY1CM/", {
        "name": "Re-Engagement | Step 2 - Quick Value",
        "subject": '{{ lead.name }} | Quick Tip for Facility Managers',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "One thing we've seen help our clients save money: matching cleaning "
            "frequency to actual foot traffic instead of a fixed schedule.<br><br>"
            "For example, lobbies and restrooms might need daily attention, but "
            "conference rooms and back offices can often go to 2-3x per week — "
            "saving 15-20% on cleaning costs without any drop in quality.<br><br>"
            "If you'd like, I can take a look at your space and suggest an optimized "
            "schedule. Takes about 15 minutes and it's completely free.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done")

    # Re-Engagement Step 3 reuses Commercial Step 4 (walkthrough offer) — no change needed

    # -----------------------------------------------------------------
    # Post-Walkthrough Step 1 (tmpl_P8zKTupsdu5WA3kSJ2WvBYUPgEWtWQF9fNKewwTVtLE)
    # Update sign-off to Sentel
    # -----------------------------------------------------------------
    print("\n  Rewriting: Post-Walkthrough Step 1 (sign-off update)...")
    api_put("email_template/tmpl_P8zKTupsdu5WA3kSJ2WvBYUPgEWtWQF9fNKewwTVtLE/", {
        "name": "Post-Walkthrough | Step 1 - Custom Quote",
        "subject": "{{ lead.name }} | Your Custom Cleaning Quote from Scrub Squads",
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Great meeting you today! As promised, I'm putting together your custom "
            "cleaning proposal based on what we saw during the walkthrough.<br><br>"
            "You should have the full quote in your inbox within 24 hours. It will include:<br><br>"
            "- Scope of work tailored to your space<br>"
            "- Recommended cleaning frequency<br>"
            "- Transparent pricing with no hidden fees<br><br>"
            "In the meantime, if you have any questions or want to adjust anything we "
            "discussed, just reply to this email.<br><br>"
            "Looking forward to working with you!<br><br>"
            f"{SIG_SENTEL}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Post-Walkthrough Step 2 (tmpl_Q10aXOJbajZwpXs0XXcJW8D4eOxVf4bo0uJcKjsiuFu)
    # -----------------------------------------------------------------
    print("  Rewriting: Post-Walkthrough Step 2 (sign-off update)...")
    api_put("email_template/tmpl_Q10aXOJbajZwpXs0XXcJW8D4eOxVf4bo0uJcKjsiuFu/", {
        "name": "Post-Walkthrough | Step 2 - Questions",
        "subject": "{{ lead.name }} | Any Questions About the Proposal?",
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Just checking in to see if you had a chance to review the cleaning proposal "
            "I sent over.<br><br>"
            "If anything needs adjusting — different frequency, specific areas of focus, "
            "or budget considerations — I'm happy to revise it. We want to make sure it "
            "fits your needs exactly.<br><br>"
            "Feel free to reply here or give me a call at 786-838-4148.<br><br>"
            f"{SIG_SENTEL}"
        ),
        "is_shared": True
    })
    print("    Done")

    # -----------------------------------------------------------------
    # Post-Walkthrough Step 3 (tmpl_gAMb0HmbhSGLncrePYEwiNsU3XVV9gzotd35gcXUBtn)
    # -----------------------------------------------------------------
    print("  Rewriting: Post-Walkthrough Step 3 (sign-off update)...")
    api_put("email_template/tmpl_gAMb0HmbhSGLncrePYEwiNsU3XVV9gzotd35gcXUBtn/", {
        "name": "Post-Walkthrough | Step 3 - Ready When You Are",
        "subject": "{{ lead.name }} | Ready When You Are",
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Just a final follow-up on the cleaning proposal for {{ lead.name }}. "
            "I know these decisions take time, and there's no pressure.<br><br>"
            "If you'd like to move forward, we can usually start within a week of signing. "
            "If now isn't the right time, no worries at all — we'll be here when you're "
            "ready.<br><br>"
            "Either way, it was great seeing your space and I appreciate your time.<br><br>"
            f"{SIG_SENTEL}"
        ),
        "is_shared": True
    })
    print("    Done")

    # =================================================================
    # STEP 2b: Rewrite Phase 2 templates (currently unused, will go in new sequence)
    # =================================================================
    print("\n  Rewriting: Phase 2 templates (for new sequence)...")

    # Template #5 → Phase 2 Step 1
    api_put("email_template/tmpl_aHraJWP1O84rBe1bCtmDpYhW9eqh0sROgDQjkmq2N2X/", {
        "name": "Phase 2 | Step 1 - Checking Back In",
        "subject": '{{ lead.name }} | Checking Back In',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "I know I reached out a few weeks ago about cleaning services for "
            "{{ lead.name }}. Didn't want to be a pest, but I did want to make sure "
            "you knew the offer still stands.<br><br>"
            "If your current situation has changed — or if you just want to see what "
            "professional cleaning would cost for your space — we're happy to do a quick, "
            "no-obligation walkthrough.<br><br>"
            "Does this week or next work?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Phase 2 Step 1")

    # Template #7 → Phase 2 Step 2 (post-construction angle)
    api_put("email_template/tmpl_m1TrO5fIx9UENXaPNcArs2NcQcCY8WBbxbgtbMJGalX/", {
        "name": "Phase 2 | Step 2 - Post-Construction",
        "subject": '{{ lead.name }} | Renovating? We Handle the Cleanup',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Quick heads up — besides regular janitorial services, we also specialize "
            "in post-construction cleaning.<br><br>"
            "If you're planning any renovations, build-outs, or tenant improvements "
            "this year, we can handle everything from dust removal to final detailing — "
            "getting the space move-in ready, fast.<br><br>"
            "Something to keep in mind for future projects. Happy to discuss anytime.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Phase 2 Step 2")

    # Template #8 → Phase 2 Step 3 (health/disinfection angle)
    api_put("email_template/tmpl_GmX2w4aVgi902fUUWpW2iCxBLeCbMGrCyqzjHl2EOXb/", {
        "name": "Phase 2 | Step 3 - Healthier Workspace",
        "subject": '{{ lead.name }} | Fewer Sick Days Start with Better Cleaning',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Quick fact: the average office desk has 400x more bacteria than a "
            "toilet seat. Door handles, shared desks, and restrooms are the "
            "biggest culprits for spreading illness in the workplace.<br><br>"
            "Our professional disinfection services target these high-touch areas "
            "to keep your team healthy and reduce sick days — something that "
            "directly impacts your bottom line.<br><br>"
            "Would you like details on our disinfection and deep-cleaning packages?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Phase 2 Step 3")

    # Template #10 → Phase 2 Step 4 (soft close)
    api_put("email_template/tmpl_0brxO7eKluWmOc7GDYX5KtI3LvenCOii72B0sELoqGJ/", {
        "name": "Phase 2 | Step 4 - Here When You're Ready",
        "subject": '{{ lead.name }} | No Rush, Just Keeping the Door Open',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "This is my last email for now — I don't want to fill up your inbox.<br><br>"
            "If cleaning services aren't a priority right now, I completely understand. "
            "But if things change down the road — your current provider drops the ball, "
            "you're planning a renovation, or you just want a second quote — we're here.<br><br>"
            "You can reply to this email anytime or call us at 786-838-4148.<br><br>"
            "Wishing you and your team a great rest of the year.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Phase 2 Step 4")

    # =================================================================
    # STEP 3: Create 4 NEW templates (Under Contract x2, In-House x2)
    # =================================================================
    print("\n" + "=" * 60)
    print("STEP 3: Creating new templates")
    print("=" * 60)

    # Under Contract #1
    uc1 = api_post("email_template/", {
        "name": "Under Contract | Step 1 - Introduction",
        "subject": '{{ lead.name }} | Just an Introduction from Scrub Squads',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "I know {{ lead.name }} already has a cleaning provider — and if they're doing "
            "a great job, that's great. No reason to switch.<br><br>"
            "I just wanted to introduce Scrub Squads in case you ever need a backup plan "
            "or a second quote when your contract comes up for renewal. We work with offices, "
            "medical facilities, and commercial properties across South Florida.<br><br>"
            "No rush at all. Just planting a seed.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print(f"  Created: {uc1['name']} ({uc1['id']})")

    # Under Contract #2
    uc2 = api_post("email_template/", {
        "name": "Under Contract | Step 2 - Renewal Time",
        "subject": '{{ lead.name }} | Worth a Second Quote When Your Contract Renews',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Just a quick follow-up from a few weeks back. If your cleaning contract "
            "is coming up for renewal soon, it might be worth getting a second quote "
            "before you re-sign.<br><br>"
            "We offer:<br><br>"
            "- Month-to-month flexibility (no long-term lock-in)<br>"
            "- A free walkthrough with a custom proposal in 24 hours<br>"
            "- Transparent pricing with no hidden fees<br><br>"
            "Even if you end up staying with your current provider, having a comparison "
            "gives you leverage to negotiate better terms.<br><br>"
            "Happy to set up a walkthrough whenever the timing makes sense.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print(f"  Created: {uc2['name']} ({uc2['id']})")

    # In-House #1
    ih1 = api_post("email_template/", {
        "name": "In-House | Step 1 - Your Team Has Better Things to Do",
        "subject": '{{ lead.name }} | Is Cleaning Pulling Your Team Away?',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Managing an in-house cleaning team takes more time than most people realize — "
            "hiring, training, buying supplies, covering sick days, handling complaints.<br><br>"
            "A lot of our clients started the same way and switched to outsourced cleaning "
            "because it freed up their team to focus on what they were actually hired to do.<br><br>"
            "If you've ever wondered whether outsourcing would save you time or money, "
            "I'd be happy to run a quick comparison — no cost, no obligation.<br><br>"
            "Just reply and I'll put something together.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print(f"  Created: {ih1['name']} ({ih1['id']})")

    # In-House #2
    ih2 = api_post("email_template/", {
        "name": "In-House | Step 2 - Hidden Costs",
        "subject": '{{ lead.name }} | The Hidden Costs of In-House Cleaning',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "Here's something we see often: the true cost of in-house cleaning "
            "is usually 30-40% higher than what shows up on the payroll.<br><br>"
            "When you add up supplies, equipment maintenance, workers' comp insurance, "
            "training, coverage for sick days and turnover, and the management time "
            "to oversee it all — the numbers add up fast.<br><br>"
            "Outsourcing to a professional team typically costs less per square foot "
            "and eliminates those hidden expenses entirely.<br><br>"
            "If you're curious, I can do a free walkthrough and put together a side-by-side "
            "comparison for {{ lead.name }}. Takes 15 minutes and you'll have real numbers "
            "to work with.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print(f"  Created: {ih2['name']} ({ih2['id']})")

    # Also clean up: rewrite the unused "1. Commercial" and "Commercial | 3rd" templates
    # that are not in sequences but have typos
    print("\n  Cleaning up unused templates with typos...")

    # "1. Commercial Email Campaign" — not in sequence, different from "Commercial | 1st"
    api_put("email_template/tmpl_VfHmvhnTLnk4YKs2CFPVr96CYZOnVAYWOHMZ2DhWI5T/", {
        "name": "Commercial | Intro (Alternate)",
        "subject": '{{ lead.name }} | Could We Stop By for an Introduction?',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "We're a South Florida cleaning company serving offices, property managers, "
            "medical and educational facilities, and construction sites across the region.<br><br>"
            "Our focus is simple: reliable, consistent, professional cleaning so you can "
            "focus on running your business — not chasing down your cleaning crew.<br><br>"
            "Would it make sense to stop by for a quick introductory meeting? "
            "No pressure, just opening the door for a conversation.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Commercial Intro (Alternate)")

    # "Commercial | 3rd" — has "quik" typo
    api_put("email_template/tmpl_f8gouYa1OnNb6CSSlwxIOkRHFt7MLWpG0pIuJdiSsLF/", {
        "name": "Commercial | Follow-Up (Alternate)",
        "subject": '{{ lead.name }} | Clean Office, No Hassle',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "We'd love to help keep your workspace clean and professional, "
            "with no disruptions to your team.<br><br>"
            "We can provide a detailed plan that fits your hours and budget.<br><br>"
            "Are you available this or next week for a quick walkthrough?<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Commercial Follow-Up (Alternate)")

    # Pricing Guide - Post-Construction (clean up sign-off)
    api_put("email_template/tmpl_OU3cRDG7koo5Eh56pAjaGZdqTQx6PonQeYeQ45v2sgf/", {
        "name": "Pricing Guide - Post-Construction",
        "subject": '{{ lead.name }} | Post-Construction Cleaning Rates in South Florida',
        "body": (
            'Hi {{ contact.first_name | default:"there" }},<br><br>'
            "We support contractors and project teams with post-construction cleaning "
            "across South Florida.<br><br>"
            "For quick budgeting, here's a general pricing reference (per SQFT):<br><br>"
            "<b>Rough Cleaning: $0.22 - $0.32/sqft</b><br>"
            "- $0.22-$0.25 for large footprints, light debris, flexible timeline<br>"
            "- $0.26-$0.32 for restaurants, retail, tighter deadlines<br><br>"
            "<b>Final Cleaning: $0.25 - $0.35/sqft</b><br>"
            "- $0.25-$0.28 for standard commercial spaces<br>"
            "- $0.29-$0.35 for restaurants, detailed interiors, inspection-ready finishes<br><br>"
            "Pricing varies based on site condition, access, and scope. Final numbers are "
            "always confirmed after a walkthrough.<br><br>"
            "If you have an upcoming project, I'm happy to take 5 minutes to understand "
            "the scope and see if we're a fit.<br><br>"
            f"{SIG_CHRISTIAN}"
        ),
        "is_shared": True
    })
    print("    Done: Post-Construction Pricing Guide")

    # =================================================================
    # Summary
    # =================================================================
    print("\n" + "=" * 60)
    print("TEMPLATE REWRITE COMPLETE")
    print("=" * 60)
    print("  Deleted: 4 stale templates")
    print("  Rewritten: 15 active templates")
    print("  Created: 4 new templates")
    print(f"    - Under Contract Step 1: {uc1['id']}")
    print(f"    - Under Contract Step 2: {uc2['id']}")
    print(f"    - In-House Step 1: {ih1['id']}")
    print(f"    - In-House Step 2: {ih2['id']}")

    # Save new template IDs for the sequence builder
    new_ids = {
        "under_contract_1": uc1["id"],
        "under_contract_2": uc2["id"],
        "in_house_1": ih1["id"],
        "in_house_2": ih2["id"],
    }
    with open(".tmp/new_template_ids.json", "w") as f:
        json.dump(new_ids, f, indent=2)
    print("\n  Template IDs saved to .tmp/new_template_ids.json")


if __name__ == "__main__":
    main()
