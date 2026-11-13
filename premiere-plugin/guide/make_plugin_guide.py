from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

OUT = "/Users/joshuapeters/Downloads/P Corp POST Plugin Guide.pdf"
LOGO = "/Users/joshuapeters/Desktop/Alpha Mode Master Folder/Alpha Mode Media Brand Assets/logo_icon_edc717.png"
INK, MUTED, LINE, GOLD, TINT, SOFT = colors.HexColor("#15171B"), colors.HexColor("#5C6370"), colors.HexColor("#D9DCE1"), colors.HexColor("#EDC717"), colors.HexColor("#FBF6D9"), colors.HexColor("#F4F5F6")
W, H = A4
M = 18 * mm
CONTENT = W - 2 * M

body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.6, leading=13.6, textColor=INK, alignment=TA_LEFT, spaceAfter=5)
lead = ParagraphStyle("lead", parent=body, fontSize=10.6, leading=15, spaceAfter=8)
h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=15.5, leading=19, spaceBefore=4, spaceAfter=2)
h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=10.8, leading=14, spaceBefore=9, spaceAfter=4)
cell = ParagraphStyle("cell", parent=body, fontSize=8.7, leading=11.9, spaceAfter=0)
head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", fontSize=7.6, leading=10, textColor=MUTED)
note = ParagraphStyle("note", parent=body, fontSize=9.1, leading=12.8, spaceAfter=0)
num = ParagraphStyle("num", parent=cell, fontName="Helvetica-Bold", textColor=MUTED)
phase = ParagraphStyle("phase", parent=cell, fontName="Helvetica-Bold", fontSize=8.9, textColor=colors.white)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=11, bulletIndent=1, spaceAfter=3.5)


def P(t, s=cell):
    return Paragraph(t, s)


def section(title, intro=None):
    rule = Table([[""]], colWidths=[26], rowHeights=[2.4])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    rule.hAlign = "LEFT"
    out = [Spacer(1, 7), Paragraph(title, h1), rule, Spacer(1, 6)]
    if intro:
        out.append(Paragraph(intro, body))
    return out


def table(headers, rows, widths, repeat=True):
    data = [[P(x.upper(), head) for x in headers]] + [[P(c) for c in r] for r in rows]
    t = Table(data, colWidths=[CONTENT * w for w in widths], repeatRows=1 if repeat else 0)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.6),
    ]))
    return t


def callout(text):
    t = Table([[Paragraph(text, note)]], colWidths=[CONTENT])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TINT), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def bullets(items):
    return [Paragraph(i, bullet, bulletText="•") for i in items]


def steps(groups):
    rows, style = [], [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.4)]
    n = 0
    for title, where, items in groups:
        i = len(rows)
        rows.append([Paragraph(f"{title} <font name='Helvetica' size='8.2' color='#C9CDD3'>&nbsp;&nbsp;{where}</font>", phase), "", ""])
        style += [("SPAN", (0, i), (-1, i)), ("BACKGROUND", (0, i), (-1, i), INK), ("LEFTPADDING", (0, i), (-1, i), 7), ("TOPPADDING", (0, i), (-1, i), 3.6), ("BOTTOMPADDING", (0, i), (-1, i), 4.2)]
        for what, extra in items:
            n += 1
            j = len(rows)
            rows.append([P(str(n), num), P(what), P(extra)])
            style += [("LINEBELOW", (0, j), (-1, j), 0.4, LINE), ("LEFTPADDING", (0, j), (0, j), 7)]
    t = Table(rows, colWidths=[CONTENT * .06, CONTENT * .5, CONTENT * .44])
    t.setStyle(TableStyle(style))
    return t


def first_page(c, d):
    c.saveState()
    band = 50 * mm
    c.setFillColor(INK)
    c.rect(0, H - band, W, band, stroke=0, fill=1)
    c.drawImage(LOGO, M, H - 21 * mm, width=10 * mm, height=9.5 * mm, mask="auto", preserveAspectRatio=True)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 25)
    c.drawString(M, H - 34 * mm, "P Corp POST for Premiere Pro")
    c.setFillColor(colors.HexColor("#C9CDD3"))
    c.setFont("Helvetica", 11.5)
    c.drawString(M, H - 41.5 * mm, "How to use the plugin, and when to use each feature")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(W - M, H - 17 * mm, "November 2026")
    footer(c, d)
    c.restoreState()


def later_page(c, d):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(M, H - 11 * mm, "P Corp POST for Premiere Pro")
    c.setStrokeColor(LINE)
    c.setLineWidth(0.4)
    c.line(M, H - 13 * mm, W - M, H - 13 * mm)
    footer(c, d)
    c.restoreState()


def footer(c, d):
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawRightString(W - M, 10 * mm, str(d.page))


doc = BaseDocTemplate(OUT, pagesize=A4, title="P Corp POST for Premiere Pro: plugin guide", author="Alpha Mode Media", subject="How to use the plugin, and when to use each feature", leftMargin=M, rightMargin=M)
doc.addPageTemplates([
    PageTemplate(id="first", frames=[Frame(M, 15 * mm, CONTENT, H - 15 * mm - 54 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=first_page),
    PageTemplate(id="later", frames=[Frame(M, 15 * mm, CONTENT, H - 15 * mm - 17 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=later_page),
])

s = [NextPageTemplate("later")]
s.append(Paragraph("This plugin and the P Corp app take a shoot from memory card to an organised, part-cut Premiere project. They copy, log and assemble, and suggest moments. You stay the editor.", lead))
s += section("What do you want to do?")
s.append(table(["You want to", "Use", "Where"], [
    ["Get a cut to music built for you", "<b>Plan Edit</b>, then <b>Build My Edit</b>", "P Corp app, then plugin"],
    ["Organise a shoot and choose your selects", "<b>Log This Shoot</b>, then <b>Apply Shoot Log</b>", "Plugin, under More"],
    ["Plan the shots, then check you got them", "<b>Coverage Plans</b>", "P Corp app"],
    ["Share a live shot list with the crew", "<b>Make phone link</b>, on a coverage plan", "P Corp app or phone"],
    ["Reuse a shot list for similar shoots", "<b>New plan</b> from a template, or <b>Save as template</b>", "P Corp app"],
    ["Find soundbites in speech or interviews", "<b>Transcribe Dialogue</b>, then <b>Suggest Smart Selects</b>", "Plugin, under More"],
    ["Cut an interview filmed on several cameras", "<b>Plan Edit</b> with the <i>Talking head, several cameras</i> style, then <b>Build My Edit</b>", "P Corp app, then plugin"],
    ["Cut a corporate story to a voice-over", "<b>Plan Edit</b> with <i>Corporate story with narration</i> and your script, then <b>Build My Edit</b>", "P Corp app, then plugin"],
    ["Lay out best moments with no music", "<b>Detect Highlights</b>, then <b>Assemble Rough Cut</b>", "P Corp app, then plugin"],
    ["Check a card for corrupt files or duplicates", "<b>View Report</b>", "P Corp app"],
    ["Teach it how you edit", "<b>Learn From My Edit</b>, once per finished edit", "Plugin"],
], [.37, .39, .24]))
s.append(Spacer(1, 9))
s.append(callout("<b>Safe by design.</b> Every build makes a new sequence and leaves your existing ones alone. Camera files are never changed, and rejecting a clip only moves it to a bin."))

s += section("Before you start")
s += bullets([
    "<b>P Corp OS has to be running on this Mac</b>, because the plugin talks to it. It needs internet to start, so use a phone hotspot at a venue.",
    "<b>Load the plugin</b> from Adobe UXP Developer Tools, again after each Premiere restart or update.",
    "<b>First time only:</b> paste your P Corp token into the panel and click Save. <b>Change Token</b> replaces it later.",
    "<b>The panel</b> shows Build My Edit and Learn From My Edit. Everything else is under <b>More</b>.",
])

s += section("Two ways to start a shoot", "<b>Start in the P Corp app whenever you can.</b> It makes a verified copy of the card, and Plan Edit, Build My Edit, Transcribe, Smart Selects, Exposure and Rough Cut all need a P Corp shoot behind the project. <b>Straight into Premiere</b> still gets you Log This Shoot, Apply Shoot Log, Coverage Plans and Learn From My Edit, but the clips stay on the card.")

s.append(PageBreak())
s += section("One shoot, start to finish", "This is the full route, in order. The next page shows what to leave out for each kind of job. If there's a brief or run sheet, start with <b>Coverage Plans</b> before the shoot, and the crew can tick it off on their phones on the day.")
s.append(steps([
    ("Copy the footage", "P Corp app, POST", [
        ("Plug in the card and your drive. Fill in the profile, shoot name, drives, format, resolution and frame rate, tick the day you shot under <b>Recorded on</b>, then click <b>Create Job</b> and <b>Start</b>.", "It copies, checks every file against the original and analyses the media. A notification says when it's ready. More than one card? Once it's ready, swap cards and click <b>Add Another Card</b> before step 3."),
        ("Optional: click <b>View Report</b>.", "Cameras, frame rates, corrupt files, exact duplicates. Its exposure flags can miss problems on S-Log3."),
    ]),
    ("Set up Premiere", "plugin, More", [
        ("Click <b>Prepare POST Project</b>.", "Makes the project and bins, imports the media and adds an empty sequence."),
    ]),
    ("Log it", "plugin, then review page", [
        ("Click <b>Log This Shoot</b>. The review page opens in your browser.", "Free. Checks, then previews, run by themselves, each about as long as the footage on 4K 50p. Frames appear within minutes."),
        ("Once the checks finish, click <b>Tag</b> on the page.", "About 1¢ a clip. Frames go to Anthropic, so skip this for a client whose terms don't allow it."),
        ("Go through the clips: <b>S</b> selects, <b>X</b> rejects, <b>Space</b> plays. Fix any tag that's wrong.", "Only your selects go in Selects. Nothing ranks them for you."),
        ("If you made a shot list: click <b>Coverage</b> at the top of the page and check the footage against it.", "Shows what's covered, weak or missing. About 1¢ a shot."),
        ("Back in Premiere, click <b>Apply Shoot Log</b>.", "Bins, search bins, notes and markers. Run it again whenever you change your mind."),
    ]),
    ("If people speak", "plugin, More", [
        ("Click <b>Transcribe Dialogue</b>, then <b>Suggest Smart Selects</b>.", "Free. Premiere transcribes, then markers land on clean sentences. Skip both if nobody speaks."),
    ]),
    ("Plan the cut", "P Corp app, Plan Edit", [
        ("Choose <b>What kind of edit?</b>, <b>Which song?</b> and <b>How long?</b>", "Clips you rejected are left out automatically, and the plan's notes list them."),
        ("Under Clip descriptions, click <b>Describe</b>.", "About 1¢ a clip, separate from Tag. It's what lets shots start on the action."),
        ("Click <b>Plan Edit</b>, then <b>Open Preview</b> and <b>Review Moments</b>.", "Keep, swap or lock shots. <b>Plan Again</b> never loses a plan: <b>Earlier plans</b> brings any back."),
        ("Optional: click <b>Add Accents</b>.", "Flashes, zooms and sound effects, if the style has them. Needs an Adjustment Layer first."),
    ]),
    ("Build and finish", "Premiere", [
        ("Save your project, then click <b>Build My Edit</b>.", "Builds the plan as a new sequence with the music on its own track."),
        ("Finish it by hand: re-cut, colour, titles.", "This is where your edit happens."),
        ("With your final sequence open, click <b>Learn From My Edit</b> once.", "Compares your cut with the plan and logs what you changed."),
    ]),
]))

s.append(PageBreak())
s += section("When to use each job", "You rarely need every step. These are the shortest routes for common jobs.")
s.append(table(["Job", "Do this", "Leave out"], [
    ["<b>Event recap or brand activation to music</b>", "Full route. Choose <i>Your usual pace</i> or an event style. Describe clips so shots start on the action.", "Transcribe and Smart Selects, unless you need a soundbite"],
    ["<b>Interview on several cameras</b>", "Copy, Prepare, Plan Edit with <i>Talking head, several cameras</i>. Pick the cameras and which one has the sound, then Build My Edit.", "Song. Rejects don't apply to the cameras you pick"],
    ["<b>Corporate story with a voice-over</b>", "Copy, Prepare, Log, Plan Edit with <i>Corporate story with narration</i>, your script and a music bed, then Build My Edit.", "Describe, unless you want it"],
    ["<b>Long-form with no music</b>", "Copy, Prepare, Transcribe, Smart Selects or Detect Highlights, then Assemble Rough Cut. To set the order, lay the clips on a sequence named after the shoot first.", "Plan Edit, Build My Edit"],
    ["<b>Footage already in Premiere</b>", "Log This Shoot, Tag, review, Apply Shoot Log. Learn From My Edit when you've finished cutting.", "Everything else: it needs a P Corp shoot"],
    ["<b>A brief with must-have shots</b>", "Coverage Plans before the shoot, a phone link for the crew on the day, then whichever route fits. Log, Tag and run the check straight after, while you can still get what's missing.", "Nothing. It sits alongside any route"],
    ["<b>Quick look at a card</b>", "Create Job, Start, View Report.", "Everything else"],
], [.27, .47, .26]))

s += section("Which style to choose", "Styles come from real edits. Each sets the pace and how cuts sit on the music.")
s.append(table(["Style", "What you get", "Use it for"], [
    ["<b>Your usual pace</b>", "Cuts on the music at the pace of your own edits, with optional brand cards.", "Your default for most music edits"],
    ["<b>JD Sports store opening</b>", "Your three JD reels: opens on the hero moment, ends on people, slow-mo marked.", "JD Sports jobs"],
    ["<b>Fast streetwear reel</b>", "Quick cuts on the beat, with flash and zoom accents.", "Retail and streetwear launches"],
    ["<b>Fashion event highlight</b>", "A music-driven launch-event highlight.", "Fashion events"],
    ["<b>GQ x Miele event reel</b>", "On the beat, with a quick open, a steady middle, a faster build and a slow logo ending. Shots start on the action.", "Premium brand events"],
    ["<b>Expo and product highlight</b>", "A music-driven vertical reel.", "Expos and showrooms"],
    ["<b>Energy-drink reel</b>", "A fast vertical highlight, cut on the music.", "High-energy product work"],
    ["<b>Food and drink promo (estimated)</b>", "An estimated rhythm blended from three of your edits, not measured from a real food edit.", "Food and drink, as a starting point"],
    ["<b>Calm corporate highlight</b>", "About two seconds a shot, with brand cards.", "Only when a client wants it calm: it's far slower than your usual edits"],
    ["<b>Corporate story with narration</b>", "Calm b-roll paced by your script, one phrase per shot.", "Voice-over pieces"],
    ["<b>Talking head, several cameras</b>", "Lines up the cameras by sound and switches angle at the pauses.", "Interviews"],
], [.28, .45, .27]))

s.append(PageBreak())
s += section("The plugin, button by button")
wid = [.19, .42, .20, .19]
s.append(table(["Button", "What it does", "Use it when", "Skip it when"], [
    ["<b>Build My Edit</b>", "Builds your saved plan as a new sequence: cuts, music, accents, brand cards. Sets up the next ready shoot first if it needs to.", "You have a plan you're happy with", "You haven't planned in the P Corp app"],
    ["<b>Learn From My Edit</b>", "Saves the project, then compares the open sequence with the plan and logs it. Changes nothing else.", "Once per finished edit, on any project", "It's still a stringout: it won't count clip lists"],
    ["<b>Prepare POST Project</b>", "Makes a real Premiere project for the next copied and analysed shoot: bins, media, empty sequence.", "Right after the copy finishes", "You already have a project for that shoot"],
    ["<b>Log This Shoot</b>", "Reads the project's clips and opens the review page. Changes nothing in the project.", "Every shoot worth logging", "A handful of clips you know well"],
    ["<b>Apply Shoot Log</b>", "Brings your choices into the project. Safe to run again: it doubles nothing.", "After each review", "Before you've tagged or chosen anything"],
    ["<b>Transcribe Dialogue</b>", "Runs Premiere's own transcription on clips with sound. Free, but can take minutes.", "Interviews, speeches, vox pops", "Music-driven b-roll"],
    ["<b>Suggest Smart Selects</b>", "Adds markers on clean, complete sentences in transcribed clips. Only suggestions.", "Finding soundbites fast", "No transcript yet"],
    ["<b>Apply Starting Exposure</b>", "Adds a mild Lumetri exposure nudge, up to 1 stop, to clips flagged over or underexposed.", "Normal-contrast footage with flags", "S-Log3: it will rarely do anything"],
    ["<b>Assemble Edit</b>", "The same build as Build My Edit, without the setup step.", "Rarely: Build My Edit covers it", "Most of the time"],
    ["<b>Assemble Rough Cut</b>", "Lays each clip's best moments in a new sequence, in your timeline's order or the order filmed. Expect to re-edit it.", "A cut with no music", "A cut to music. Save first on a big shoot"],
], wid))

s += section("The P Corp app")
s.append(table(["Control", "What it does", "Use it when", "Skip it when"], [
    ["<b>Create Job, Start</b>", "Copies the card and checks every file. Retry resumes where it stopped.", "Every shoot", ""],
    ["<b>Coverage Plans</b>", "Turns a brief into a shot list, then checks the footage against it. See Coverage.", "A brief names shots you must get", "Free-form shoots with no list"],
    ["<b>View Report</b>", "Cameras, formats, slow-motion clips, corrupt files, duplicates. <b>Analyze Frames</b> on a clip adds Claude's read of it, at a small cost.", "You want a quick check of what was shot", "You trust the card"],
    ["<b>More: Generate Proxies</b>", "Appears when clips would benefit. Makes smaller copies, which you attach in Premiere yourself.", "Footage is too slow to cut", "It plays well"],
    ["<b>More: Detect Highlights</b>", "Finds each clip's best moment for Rough Cut. Sends frames to Claude several times per clip, so it costs more than Tag.", "Before Rough Cut on footage with no speech", "You're cutting to music"],
    ["<b>Plan Edit: Advanced options</b>", "Where in the song to start, an opening clip, brand cards (needs a logo in the graphics folder), accents and sound effects.", "You want more control", "The defaults look right"],
    ["<b>Review Moments</b>", "Keep, swap or <b>Lock</b> each shot. <b>Regenerate shots</b> re-picks a run you don't like.", "Before every build", "Never: your taste goes in here"],
], wid))

s.append(PageBreak())
s += section("The Shoot Log review page")
keys = Table([[P(k, ParagraphStyle("k", parent=cell, fontName="Courier-Bold", alignment=1)), P(v)] for k, v in [("S", "Select the clip, or clear it if it's already selected"), ("X", "Reject the clip, or clear it if it's already rejected"), ("U", "Back to undecided"), ("Arrows", "Move between clips"), ("Space", "Play or pause"), ("Enter", "Open or close the detail panel"), ("Esc", "Close the panel")]], colWidths=[CONTENT * .13, CONTENT * .87])
keys.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (0, -1), SOFT), ("LINEBELOW", (0, 0), (-1, -1), 2, colors.white), ("LEFTPADDING", (1, 0), (1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 2.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2)]))
s.append(keys)
s.append(Paragraph("What the checks mean", h2))
s.append(table(["Label", "Meaning", "What to do"], [
    ["<b>Clean</b>", "Nothing stood out.", "Judge it by eye as normal."],
    ["<b>To check</b>", "Soft or low detail, dark, very bright, clipping, crushed shadows, shaky, short, or looks like another clip. Limits follow the clip's real gamma, read from Sony's sidecar file.", "A note, not a verdict. In your finished HAUS cut, flagged clips turned up about as often as in the clips you left out, and one flagged \"soft\" here was a plain board that was perfectly sharp."],
    ["<b>Unusable</b>", "Can't be read, or black for nearly its whole length.", "Rejected for you. Press U to bring it back."],
], [.14, .46, .40]))
s.append(Paragraph("Nothing ranks your clips, on purpose. When tested against your real edits, sorting by Claude's rating did no better than chance, so Selects only ever holds what you choose.", ParagraphStyle("after", parent=body, spaceBefore=7)))
s.append(Paragraph("What you get in Premiere", h2))
s += bullets([
    "<b>Shoot Log bin:</b> Selects and Rejects hold those clips. A clip with no choice stays where it was, and one you un-choose moves back out to the top of the project.",
    "<b>By Subject and By Shot Size:</b> search bins that show matching clips without copying them. <b>By Moment</b> joins them once a coverage check has run.",
    "<b>Log Note column:</b> your tags as single words, such as <font name='Courier'>subjectproduct</font> or <font name='Courier'>shotwide</font>. Type one into the Project panel search to find those clips.",
    "<b>Description column:</b> the one-line description. One you type yourself is never overwritten.",
    "<b>Good column:</b> ticked for selects. <b>Markers:</b> on the moments Claude described.",
])
s.append(Spacer(1, 4))
s.append(callout("<b>Don't delete a clip from inside a search bin.</b> That removes it from the project. Remove clips from the bin where they really live."))
s.append(Paragraph("Handy to know", h2))
s += bullets([
    "<b>Previews</b> show at the top of the page as they're made. Click <b>Pause</b> to free up the Mac. A clip you click still gets made straight away.",
    "<b>Tag</b> shows the price first and stops itself at a limit. If the signal drops, what's done is saved: click it again to carry on.",
    "<b>Thumbnails and previews</b> use a viewing curve so S-Log3 is easy to judge. Your footage isn't changed.",
    "<b>Group and filter</b> at the top of the page: by subject or shot size, by checks, or by searching notes and names.",
    "<b>CSV</b> at the top of the page downloads every clip with its tags and your choices. <b>Coverage</b> beside it opens this shoot's shot list and report.",
])

s.append(PageBreak())
s += section("Coverage: did you get every shot?", "A list of the shots you must get, made before the shoot, and a check of the footage against it afterwards. Open it with <b>Coverage Plans</b> in the POST screen of the P Corp app, or <b>Coverage</b> on the Shoot Log review page.")
s.append(steps([
    ("Before the shoot", "Shot list tab", [
        ("Click <b>New plan</b> and name it. Paste the brief, run sheet or storyboard notes, or add files, then click <b>Draft shot list</b>.", "PDF, Word, Excel, CSV or images. The brief goes to Anthropic. About 1¢ for a one-page brief. Or skip the draft: start from a template, or use <b>Add a shot</b>."),
        ("Read every line. Change the wording, moment, time, size, priority or who's shooting it. Add or remove shots.", "It's only ever a draft. Set <b>Must have</b> with care: those are what the report warns you about."),
        ("Click <b>Approve list</b>, then <b>Shot list PDF</b>.", "Tick boxes, grouped by moment, for set. Changing a shot later clears the approval."),
    ]),
    ("After the shoot", "Report tab", [
        ("Run <b>Log This Shoot</b> and <b>Tag</b>, then pick the shoot under <b>Link the shoot</b>.", "One plan per shoot. A plan made from the review page's Coverage button is linked for you."),
        ("Click <b>Check</b>. It shows the price and its limit first.", "Frames go to Anthropic. It looks across every clip, then looks closely at up to 5 for each shot. About 1¢ a shot."),
        ("Read the results and look at the frames. Click <b>Covered</b>, <b>Weak</b> or <b>Missing</b> to overrule one, and click it again to undo.", "Your call always wins. The report says how many results a person confirmed."),
        ("Click <b>Report PDF</b> for a producer or client.", "Counts, must-haves not found, proof frames. No file paths or costs."),
        ("Click <b>Apply Shoot Log</b> in Premiere.", "Adds <b>By Moment</b> search bins: the clips the check tied to each moment on your list."),
    ]),
]))
s.append(Paragraph("What the results mean", h2))
s.append(table(["Result", "Meaning", "What to do"], [
    ["<b>Covered</b>", "Clearly seen in at least one clip you haven't rejected.", "Look at the frames before you rely on it."],
    ["<b>Weak</b>", "The subject is there but not as asked, only partly, or only in a clip you rejected.", "Decide if it's enough, or get a better one."],
    ["<b>Missing</b>", "Not found in the frames it looked at.", "<b>Look by eye before you tell anyone.</b> It samples frames, so it can miss a short moment."],
    ["<b>Not checked</b>", "No check has reached this shot, or you've changed it since.", "Click Check. It never counts as missing."],
], [.14, .46, .40]))
s.append(Spacer(1, 8))
s += bullets([
    "<b>Check</b> only pays for shots that haven't been checked. <b>Check all again</b> redoes the lot at full price.",
    "<b>Rejecting a clip later</b> updates the report at no charge: a shot seen only in that clip drops to Weak.",
    "<b>Templates:</b> pick one under <b>New plan</b>, or use <b>Add from template</b> on a list. <b>Save as template</b> keeps any list. <i>JD store opening</i> and <i>Brand activation</i> are there to start with. Times stay behind, so add this shoot's: one time per moment is enough for the phone warnings.",
])
s.append(Spacer(1, 4))
s.append(callout("<b>Tested on one real shoot so far.</b> On Birkenstock, with a test brief, all 4 shots that weren't filmed came out Missing, and the 9 that were came out Covered (7) or Weak (2). It leans strict, so a shot you'd happily use can say Weak. One shoot isn't much, so check Missing shots by eye before a report goes to a client."))

s.append(PageBreak())
s += section("On set: one live list for the crew", "Everyone shooting sees the same list on their own phone, and sees each other's ticks within seconds. There's no app or login: it opens in the phone's browser.")
s.append(steps([
    ("Before the shoot", "Coverage Plans, Shot list tab, On set", [
        ("Approve the list, check the shoot date, and click <b>Make phone link</b>.", "Puts a copy of the list on P Corp's cloud server. Free."),
        ("Click <b>Copy link</b> and send it to your crew, or <b>QR code</b> for them to scan.", "WhatsApp is fine. Anyone with the link can see and tick this one list, so treat it like a door code."),
    ]),
    ("On the day", "on each phone", [
        ("Open the link and pick your camera or name.", "It needs signal the first time. After that it reopens without any."),
        ("Tap a shot when you've got it. Tap again to undo.", "Everyone sees it within about 5 seconds, with who and when. <b>Note</b> adds a few words."),
        ("Or tap the mic, say what you got, and confirm.", "\"Logo wall, wide and tight\" suggests both shots. Nothing ticks until you confirm. If the mic won't work, use the keyboard's own mic in the same box."),
        ("Watch the banner at the top.", "It warns about must-haves still to get: 30 minutes before each run-sheet moment, during it, and after. Only on the shoot day, and only for moments with a clock time."),
    ]),
    ("After the shoot", "Coverage Plans", [
        ("Log, Tag and <b>Check</b> as usual.", "Ticks never decide what's covered. A shot ticked on set but not found in the footage gets its own warning, on the page and in the report PDF: look for it by eye."),
        ("Click <b>Stop link</b> when you're done.", "Phones lose the list straight away and it comes off them. Ticks stay for the report. If you forget, the link runs out 3 days after the shoot."),
    ]),
]))
s.append(Paragraph("Handy to know", h2))
s += bullets([
    "<b>No signal:</b> keep ticking. Ticks are saved on the phone and sent when signal returns, with the time they were really made.",
    "<b>Changing the list:</b> an edit on the Mac reaches phones by itself. With no signal, the page says <i>Phones have an older list</i> and offers <b>Send update</b>.",
    "<b>Filters:</b> <i>Still to get</i> hides what's ticked. <i>Mine</i> shows shots assigned to your camera, if the list says who's shooting what.",
    "<b>What the link can do:</b> see this one list and tick it. It can't reach anything else in P Corp, change the list, stop the link or spend money. A shoot under a strict NDA shouldn't use it, because the list goes on the cloud server and stays there after the link stops, closed to the crew, until you delete it.",
    "<b>Warnings only show while the page is open.</b> Nothing reaches a phone in a pocket.",
])
s.append(Spacer(1, 4))
s.append(callout("<b>Not run on a real shoot yet.</b> Tested with two browsers on test data, and by you on a real phone, where ticks came through. Try the mic again before a shoot: it only partly worked the first time."))

s.append(PageBreak())
s += section("On your phone: no Mac needed", "Make, change and send shot lists from your own phone, and draft them from a brief. Set it up once on the Mac, before the day. Your crew's side doesn't change.")
s.append(steps([
    ("Set up once", "Coverage Plans, My phone", [
        ("On the Mac, click <b>My phone</b>, then <b>Set up a phone</b>. Point your phone's camera at the QR code and open the link.", "It works once, for 15 minutes. No password to type."),
        ("Bookmark that page.", "Scan it yourself: the first phone to scan gets the login. The page only opens on your phone, so its address is useless to anyone else. Clearing Safari's data logs you out, and then you need a new QR code."),
    ]),
    ("Any time", "on your phone", [
        ("Tap <b>New shot list</b>. Start from a template, from a brief, or from nothing.", "Set the shoot date here: the warnings only run on that day."),
        ("For a brief, paste it or add a photo or file, then tap <b>Draft shot list</b>.", "A photo of a run sheet works. The brief goes to Anthropic, and it isn't kept. About 1¢ for a one-page brief. Read the result through."),
        ("Tap a shot to change or remove it. Tap a moment's <b>Add time</b> to set its time.", "One time per moment. Changes reach the crew by themselves."),
        ("Tap <b>Send to crew</b> to share the link, or <b>QR code</b> for them to scan.", "They open it, pick a name and tick. To tick yourself, tap <b>Open the checklist to tick</b>."),
        ("Watch ticks come in. <b>Details</b> changes the name or date, and stops the link.", "A stopped link stays dead. Making a new one gives a new address to send, and keeps the ticks."),
    ]),
    ("Back at the Mac", "Coverage Plans", [
        ("Open Coverage Plans.", "Your lists come in by themselves, with their ticks. The list picker shows each one's date and whether its link is live. Log, Tag and <b>Check</b> as usual: the footage check and report stay on the Mac."),
    ]),
]))
s.append(Paragraph("Handy to know", h2))
s += bullets([
    "<b>Lost your phone?</b> On the Mac, <b>My phone</b>, <b>Turn off</b> locks it out at once. Crew links it sent keep working, so stop any you need to.",
    "<b>Only you start or stop links.</b> That takes your Mac or this phone. Crew can only see and tick. They could forward their link to someone else, who could then see and tick too, until you stop it.",
    "<b>What it can do:</b> shot lists only. It can't reach anything else in P Corp.",
    "<b>Deleting a stopped list:</b> <b>Details</b> on your phone takes it off the cloud and your phone, and the Mac keeps its copy. <b>Delete list</b> in Coverage Plans takes it off the Mac and the cloud, with its ticks and report. It can't be undone, and a live link has to be stopped first.",
    "<b>A daily limit on drafts:</b> 15 a day or $1.50 a day from phones, whichever comes first, so a lost phone can't run up a bill. Templates and hand edits have no limit.",
    "<b>Both sides stay level:</b> edit on the Mac or the phone and the other catches up. If you edit the same list on both at once, the last one sent wins.",
    "<b>It needs signal</b> to make or change a list. Ticking on the crew's page is what works without it.",
])
s.append(Spacer(1, 4))
s.append(callout("<b>Not run on a real shoot yet.</b> Tried on a real iPhone: setup, a real draft from a made-up brief, and a tick on a list made on the phone all worked. How long the login lasts over days is unknown, so open the page the day before a shoot."))

s.append(PageBreak())
s += section("Time and cost", "Measured on real shoots unless it says otherwise. Your numbers will vary with footage and drive speed.")
s.append(table(["Step", "Time", "Cost"], [
    ["Copy and verify", "Depends on the drive", "Free"],
    ["Shoot Log checks", "10 min for 48 clips (11 min of 4K 50p off a card)", "Free"],
    ["Previews", "Under 11 min for 46 of those clips, in the background", "Free. 35 MB of disk"],
    ["Tag", "9 min for 48 clips", "$0.53 for 48 clips, about 1¢ each"],
    ["Apply Shoot Log", "About 6 s for 150 clips (test clips)", "Free"],
    ["Describe clips", "38 min for 165 clips", "About 1¢ a clip"],
    ["Transcribe Dialogue", "Minutes, depending on length", "Free"],
    ["Detect Highlights", "Not measured here", "More per clip than Tag. No measured figure yet"],
    ["Draft a shot list (Mac or phone)", "6 s for a one-page brief, on the Mac", "About 1¢, more for a long PDF"],
    ["Coverage check", "16 s for 14 shots on 48 clips", "11¢ for those, about 1¢ a shot"],
    ["On-set phone list", "Ticks show in about 5 s (test data)", "Free"],
], [.26, .44, .30]))
s.append(Spacer(1, 6))
s.append(Paragraph("<b>Tag, Describe, Detect Highlights, Analyze Frames and the coverage check send frames to Anthropic, and Draft shot list sends the brief.</b> Check first on a client with strict terms. Without them you still get the checks, your own selects, Apply, Plan Edit and a shot list you write yourself.", body))

s += section("Things to know")
s += bullets([
    "<b>Moments are suggestions.</b> Across your real edits, nothing reliably predicts which moment you'd pick. Review Moments is where a plan becomes yours.",
    "<b>Slow motion is marked, not applied.</b> Premiere's plugin API has no speed control, so slowed shots are placed at normal speed under a <i>P Corp: slow-mo 50%</i> marker. Select the clip, Cmd+R, click the chain, Speed 50%.",
    "<b>Accents need an Adjustment Layer.</b> Premiere's plugin API can't create one. Make an item called exactly <i>Adjustment Layer</i> at your sequence's size before you build, or the flashes and zoom hits are skipped. Check its size by hand: a new one can take the size of whichever sequence is active.",
    "<b>No text.</b> The plugin can't create titles. Brand cards and captions are images, so add your titles by hand.",
    "<b>Rejects apply to planning, not everything.</b> Plan Edit and Describe leave rejected clips out. Assemble Rough Cut still uses every clip, and you choose interview cameras yourself.",
    "<b>Selects don't steer the plan.</b> They're for you. A clip you rejected after planning gets a red label in Review Moments: swap it or click Plan Again.",
    "<b>The Shoot Log hasn't yet run on a real P Corp shoot.</b> So far it's only run on a project imported straight into Premiere. On your first full run, check that Build My Edit finds all its clips and that the plan's notes list your rejects.",
    "<b>Tag accuracy is unmeasured.</b> Fix tags when you notice they're wrong: that's how it gets measured.",
    "<b>Learning also runs by itself.</b> For P Corp shoots, an edit left unchanged for 45 minutes is logged from Premiere's auto-saves. The Learn button gives you the result straight away.",
])

s.append(PageBreak())
s += section("If something goes wrong")
s.append(table(["What you see", "What to do"], [
    ["The panel is gone or blank", "Load the plugin again in UXP Developer Tools. It needs this after every Premiere restart."],
    ["A new button is missing", "Reload the plugin after an update. It's under More."],
    ["\"This project hasn't been logged yet\", or Link the shoot lists nothing", "Click Log This Shoot first, with the right project open."],
    ["\"Nothing to apply yet\"", "Tag clips or make a choice on the review page first."],
    ["A must-have says Missing, but you shot it", "Find the clip by eye, then click Covered. The check only sees sampled frames."],
    ["A shot says Not checked", "You changed it, or the check stopped before it got there. Click Check: only those shots are charged."],
    ["A phone says \"This link isn't active\"", "It was stopped or ran out. Make a new link and send it again."],
    ["A phone says \"No signal\"", "Keep ticking. Ticks are saved and sent when signal returns."],
    ["\"Phones have an older list\"", "Click Send update on the Coverage page."],
    ["Make phone link or Plan Edit is greyed out", "Approve the list first. Plan Edit gives its reason just underneath, usually a missing song."],
    ["\"The source and destination are the same drive\"", "Choose a different destination drive, so the footage isn't on it twice."],
    ["\"Everything on that card is already in this shoot\"", "That card's been copied. Check you've put in the next one."],
    ["\"A different card is connected\"", "Put back the card it was copying, then click Retry. Or click <b>Carry On Without Unfinished Files</b>."],
    ["A list or PDF says \"not approved yet\"", "A shot or time changed since you approved it, on the Mac or your phone. Click <b>Approve list</b>. The crew's link keeps working either way."],
    ["Your phone says \"This phone isn't set up\"", "It was turned off, or Safari's data was cleared. Make a new QR code on the Mac: Coverage Plans, My phone."],
    ["\"That QR code has been used or has run out\"", "Make a new one on the Mac. Each works once, for 15 minutes."],
    ["\"That's the most drafts allowed from a phone in a day\"", "Add shots by hand, start from a template, or draft on the Mac."],
    ["\"Run Prepare POST Project\" or no job found", "That button needs a P Corp shoot behind the project. See Two ways to start a shoot."],
    ["A shot's slot is empty after a build", "The panel names the clip: it isn't in the project. Import it and build again."],
    ["Flashes and zooms are missing", "Make an Adjustment Layer at your sequence's size, then build again."],
    ["The review page asks for a token", "Paste the same token you gave the plugin. It stays in that browser."],
    ["\"The drive isn't connected\"", "Plug it back in. Nothing is lost, so try again."],
    ["Previews paused by themselves", "The card or drive was removed, or the drive is nearly full. Fix that and click Resume."],
    ["Tag or Describe stops", "Check your Anthropic credit and your signal, then click again. Finished clips are kept."],
    ["P Corp won't answer", "It needs internet to start. Check your connection, then restart the P Corp app."],
], [.38, .62]))

doc.build(s)
print("built")
