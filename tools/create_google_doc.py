#!/usr/bin/env python3
"""Create a Google Doc with Scrub Squad's cold calling script for VAs.

Usage:
    python tools/create_google_doc.py

Requires:
    GOOGLE_SERVICE_ACCOUNT_JSON  — env var with service account credentials

Output:
    Creates a Google Doc and prints the shareable URL.
"""

import json
import os
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def get_credentials():
    """Build credentials from the service account JSON env var."""
    sa_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return service_account.Credentials.from_service_account_info(
        sa_json, scopes=SCOPES
    )


# ---------------------------------------------------------------------------
# Script content
# ---------------------------------------------------------------------------

DOC_TITLE = "Scrub Squad - Cold Calling Script (VA Guide)"

# Each section is a list of (style, text) tuples.
# Styles: "TITLE", "HEADING_1", "HEADING_2", "HEADING_3", "NORMAL", "BOLD_NORMAL"
SCRIPT_SECTIONS = [
    # ── Title ──
    ("TITLE", DOC_TITLE),

    # ── Overview ──
    ("HEADING_1", "Overview"),
    ("NORMAL",
     "This script is for calling decision-makers at commercial businesses "
     "in South Florida. These are people responsible for hiring cleaning "
     "services at their company — facility managers, operations managers, "
     "property managers, office managers, and owners of smaller businesses.\n\n"
     "Your goal on every call: Book a FREE walkthrough / site visit.\n\n"
     "You are NOT selling on the phone. You are setting the appointment."),

    # ── Before You Call ──
    ("HEADING_1", "Before You Call"),
    ("NORMAL",
     "1. Open the Contacts tab in the Google Sheet.\n"
     "2. Note the contact's full name, title, company name, and industry.\n"
     "3. Have their phone number and email ready.\n"
     "4. Smile before you dial — it changes your tone.\n"
     "5. Stand up if you can — it gives you more energy."),

    # ── The Script ──
    ("HEADING_1", "The Script"),

    ("HEADING_2", "Step 1: Opening (First 10 Seconds)"),
    ("NORMAL",
     'Hi, this is [YOUR NAME] calling from Scrub Squad. '
     'Am I speaking with [CONTACT NAME]?\n\n'
     '[If yes, continue. If no: "Could you connect me with them? '
     "I'm calling about their building's cleaning services.\"]\n\n"
     "Great — I'll be brief, I know you're busy. I'm reaching out because "
     "we specialize in commercial cleaning for [INDUSTRY — e.g. property "
     "management companies / medical facilities / construction sites] "
     "here in South Florida, and I wanted to see if it makes sense for "
     "us to talk."),

    ("HEADING_2", "Step 2: Qualifying Questions"),
    ("NORMAL",
     "Ask these in a conversational tone — don't rapid-fire them:\n\n"
     '1. "Are you currently working with a cleaning company, '
     'or handling it in-house?"\n\n'
     '2. "How often are they coming in — daily, a few times a week?"\n\n'
     '3. "How has that been working out for you? Anything you wish '
     'was different?"\n\n'
     '4. "When does your current contract come up for renewal?" '
     "(or: \"Is that a month-to-month arrangement?\")\n\n"
     "LISTEN carefully. Write down their answers. Their pain points are "
     "your ammunition for the close."),

    ("HEADING_2", "Step 3: Bridge to Value"),
    ("NORMAL",
     "Based on what they share, use one of these bridges:\n\n"
     'If they have complaints:\n'
     '"That\'s actually exactly why I\'m calling. A lot of [INDUSTRY] '
     "companies in the area were dealing with the same thing before they "
     "switched to us. We've been able to [fix the specific issue they "
     "mentioned].\"\n\n"
     "If they're happy with current provider:\n"
     '"That\'s great to hear. Most of our best clients felt the same way '
     "about their previous company — until they saw the difference. "
     "What I'd love to do is just show you what we can offer so you "
     'have a benchmark."\n\n'
     "If they handle it in-house:\n"
     '"Totally understand. A lot of companies start that way. What we '
     "usually find is that outsourcing actually saves money once you "
     "factor in supplies, equipment, insurance, and the headache of "
     'managing cleaning staff. Would it be worth a quick look?"'),

    ("HEADING_2", "Step 4: The Close — Book the Walkthrough"),
    ("NORMAL",
     "This is the most important part. Be direct and confident:\n\n"
     '"Here\'s what I\'d like to do — we offer a free walkthrough where '
     "we come out, look at your space, and put together a custom quote "
     "with no obligation. It takes about 15-20 minutes. "
     'Would [DAY] or [DAY] work better for you?"\n\n'
     "Always offer two specific days (e.g. Tuesday or Thursday). "
     'Don\'t say "sometime this week" — that\'s too vague.\n\n'
     "If they agree:\n"
     '"Perfect. I\'ll have our team lead come out on [DAY] at [TIME]. '
     "What's the best address for the walkthrough? And I'll send a "
     'confirmation to [their email from the sheet]."\n\n'
     "Confirm: name, address, date, time, email. Repeat it back."),

    # ── Objection Handling ──
    ("HEADING_1", "Objection Handling"),

    ("HEADING_3", '"We already have a cleaning company."'),
    ("NORMAL",
     '"Totally understand — most of the businesses we work with did too '
     "before switching. I'm not asking you to cancel anything. "
     "Would it hurt to have a backup option with a free quote, "
     "just so you know what's out there? If we can't beat what you "
     'have, no hard feelings."'),

    ("HEADING_3", '"I\'m not interested."'),
    ("NORMAL",
     '"I hear you, and I appreciate your honesty. Quick question though — '
     "is it that you're genuinely happy with your current setup, or "
     "is it more of a timing thing? Because if it's timing, I'd love "
     'to just send you our info for when the time is right."'),

    ("HEADING_3", '"Just send me an email / some info."'),
    ("NORMAL",
     '"Absolutely, I\'ll send that right over. So I can include the '
     "right information — what's the square footage of your space, "
     "and how often are you looking for service? That way I can include "
     'a ballpark estimate with the info."\n\n'
     "[This re-engages them in conversation. After they answer, "
     'pivot back: "You know what, rather than guess on pricing over '
     "email, it'd be much more accurate if we just popped by for "
     '15 minutes. Would [DAY] work?"]'),

    ("HEADING_3", '"We\'re locked into a contract."'),
    ("NORMAL",
     '"No problem at all. When does that contract come up? '
     "[Note the date.] "
     "\"Perfect — I'll reach out about 30 days before that so you "
     "have options. In the meantime, would it be helpful to have "
     'a quote ready so you can compare when the time comes?"'),

    ("HEADING_3", '"How much does it cost?"'),
    ("NORMAL",
     '"Great question. It really depends on the size of the space, '
     "how often you need service, and what's included. That's exactly "
     "why we do the free walkthrough — so we can give you an accurate "
     "number instead of a guess. Most of our clients in [INDUSTRY] "
     "are in the range of [give a general range if you have one], "
     'but let me get you an exact quote. Would [DAY] work?"'),

    # ── Voicemail Script ──
    ("HEADING_1", "Voicemail Script (Keep Under 20 Seconds)"),
    ("NORMAL",
     '"Hi [CONTACT NAME], this is [YOUR NAME] with Scrub Squad. '
     "We do commercial cleaning for [INDUSTRY] companies in South Florida. "
     "I'd love to see if we can help with your building's cleaning needs. "
     "Give me a call back at [YOUR NUMBER], or I'll try you again "
     'in a couple of days. Thanks!"'),

    # ── Industry Tips ──
    ("HEADING_1", "Industry-Specific Talking Points"),

    ("HEADING_2", "Property Management Companies"),
    ("NORMAL",
     "Key pain points to reference:\n"
     "- Common area cleanliness directly affects tenant retention\n"
     "- Turnover cleaning between tenants needs to be fast and thorough\n"
     "- Multiple buildings = need a reliable partner who can scale\n"
     "- HOA complaints about hallways, lobbies, parking garages\n\n"
     "Power phrase: \"We help property managers keep tenants happy and "
     "buildings inspection-ready — without the headache of managing "
     'cleaning crews yourself."'),

    ("HEADING_2", "Medical Offices"),
    ("NORMAL",
     "Key pain points to reference:\n"
     "- Sanitization standards and infection control are non-negotiable\n"
     "- OSHA and health department compliance\n"
     "- Patient perception — a clean office builds trust\n"
     "- Biohazard-grade cleaning requirements\n\n"
     "Power phrase: \"We specialize in medical-grade cleaning that keeps "
     "your practice compliant and your patients comfortable. "
     'We understand the standards your facility needs to meet."'),

    ("HEADING_2", "Construction Companies"),
    ("NORMAL",
     "Key pain points to reference:\n"
     "- Post-construction cleanup needs to be done right the first time\n"
     "- Dust, debris, and paint residue from new builds\n"
     "- Final clean before client walkthroughs and inspections\n"
     "- Ongoing site maintenance during long projects\n\n"
     "Power phrase: \"We handle post-construction cleanups so your team "
     "can focus on building. We make sure the space is move-in ready "
     'before your clients walk through the door."'),

    # ── Call Tracking ──
    ("HEADING_1", "After Every Call"),
    ("NORMAL",
     "Log the result in the Google Sheet or your CRM:\n\n"
     "- BOOKED — walkthrough scheduled (date/time/address)\n"
     "- CALLBACK — they asked to be called back (note when)\n"
     "- EMAIL — sending info first (follow up in 2 days)\n"
     "- NOT INTERESTED — firm no (don't call again)\n"
     "- NO ANSWER — left voicemail (try again in 2 days)\n"
     "- WRONG NUMBER — bad contact info\n"
     "- CONTRACT LOCKED — note renewal date, follow up 30 days before\n\n"
     "The goal is to move every contact to BOOKED. "
     "If you can't do it on the first call, schedule the follow-up."),

    # ── Quick Reference ──
    ("HEADING_1", "Quick Reference Card"),
    ("NORMAL",
     "GOAL: Book a free walkthrough. That's it.\n\n"
     "TONE: Friendly, confident, professional. Never pushy.\n\n"
     "PACE: Speak slightly slower than normal. Pause after questions.\n\n"
     "SMILE: They can hear it.\n\n"
     "LISTEN: Talk 30%, listen 70%.\n\n"
     "NAME: Use their name 2-3 times during the call.\n\n"
     "NUMBERS: Aim for 40-50 calls per day, expect 8-12 conversations, "
     "target 2-3 walkthroughs booked."),
]


# ---------------------------------------------------------------------------
# Google Docs helpers
# ---------------------------------------------------------------------------

def create_doc(creds, title):
    """Create a blank Google Doc and return (doc_id, doc_url)."""
    service = build("docs", "v1", credentials=creds)
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_id, doc_url


def make_public_editable(creds, doc_id):
    """Set the doc to 'anyone with link can edit'."""
    drive = build("drive", "v3", credentials=creds)
    drive.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "writer"},
    ).execute()


def populate_doc(creds, doc_id, sections):
    """Write all script sections into the doc with formatting."""
    service = build("docs", "v1", credentials=creds)

    # Build insert requests in reverse order (Docs API inserts shift text).
    requests = []
    # We'll insert at index 1 (after the implicit empty paragraph).
    # Build content bottom-up so indices don't shift.

    # Collect all text blocks first, then insert in reverse.
    blocks = []
    for style, text in sections:
        if style == "TITLE":
            # Skip — the doc title is already set via create.
            # We'll insert it as a styled heading too.
            blocks.append((text + "\n", "TITLE"))
        elif style in ("HEADING_1", "HEADING_2", "HEADING_3"):
            blocks.append((text + "\n", style))
        else:
            blocks.append((text + "\n\n", "NORMAL_TEXT"))

    # Insert each block at index 1 in reverse so final order is correct.
    for text, named_style in reversed(blocks):
        requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": text,
            }
        })

    # Execute inserts first.
    if requests:
        service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

    # Now read the doc to find paragraph positions for styling.
    doc = service.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])

    style_requests = []
    block_idx = 0
    for element in body:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue

        para_text = ""
        for elem in paragraph.get("elements", []):
            para_text += elem.get("textRun", {}).get("content", "")

        if block_idx >= len(blocks):
            break

        expected_text, named_style = blocks[block_idx]
        if expected_text.strip() and para_text.strip() == expected_text.strip():
            start = element["startIndex"]
            end = element["endIndex"]

            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": named_style},
                    "fields": "namedStyleType",
                }
            })
            block_idx += 1

    if style_requests:
        service.documents().batchUpdate(
            documentId=doc_id, body={"requests": style_requests}
        ).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Authenticating with Google...")
    creds = get_credentials()

    print(f"Creating Google Doc: '{DOC_TITLE}'...")
    doc_id, doc_url = create_doc(creds, DOC_TITLE)

    print("Writing cold calling script content...")
    populate_doc(creds, doc_id, SCRIPT_SECTIONS)

    print("Setting sharing to 'anyone with link can edit'...")
    make_public_editable(creds, doc_id)

    print()
    print("=" * 60)
    print("  Cold calling script created!")
    print(f"  URL: {doc_url}")
    print("=" * 60)
    print()
    print("Share this link with your VA. They can view and edit it.")

    return doc_url


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
