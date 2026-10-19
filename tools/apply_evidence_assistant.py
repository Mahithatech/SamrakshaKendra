from __future__ import annotations
from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
MAIN = ROOT / "backend" / "app" / "main.py"
APP = ROOT / "frontend-react" / "src" / "App.jsx"
CSS = ROOT / "frontend-react" / "src" / "styles.css"
I18N = ROOT / "frontend-react" / "src" / "i18n.js"
MODULE_SOURCE = Path(__file__).resolve().parents[1] / "backend" / "app" / "evidence_assistant.py"
TEST_SOURCE = Path(__file__).resolve().parents[1] / "backend" / "tests" / "test_evidence_assistant.py"
DOC_SOURCE = Path(__file__).resolve().parents[1] / "docs" / "evidence-assistant.md"

for p in (MAIN, APP, CSS, MODULE_SOURCE, TEST_SOURCE, DOC_SOURCE):
    if not p.is_file():
        sys.exit(f"STOP: expected project/patch file not found: {p}. No project files were changed.")

main_text = MAIN.read_text(encoding="utf-8")
app_text = APP.read_text(encoding="utf-8")
css_text = CSS.read_text(encoding="utf-8")
i18n_text = I18N.read_text(encoding="utf-8") if I18N.exists() else None

if "SK_EVIDENCE_ASSISTANT_V1" in main_text or "SK_EVIDENCE_ASSISTANT_V1" in app_text:
    sys.exit("Evidence assistant already installed; no files changed.")

# Verify all core insertion anchors before making any edits.
import_anchor = next((x for x in (
    "from app.advanced_routes import router as advanced_router",
    "from app.india_reports_routes import router as india_reports_router",
    "from app.source_routes import router as source_router",
) if x in main_text), None)
if not import_anchor:
    sys.exit("STOP: could not find a stable router import anchor in main.py. No files changed.")
router_anchor = "app.include_router(advanced_router)"
if router_anchor not in main_text and "app.include_router(source_router)" not in main_text:
    sys.exit("STOP: could not find a stable app.include_router anchor in main.py. No files changed.")
nav_start = app_text.find("const navItems = [")
nav_end = app_text.find("];", nav_start)
if nav_start < 0 or nav_end < 0:
    sys.exit("STOP: navItems array not found in App.jsx. No files changed.")
if "id: 'assistant'" in app_text or 'id: "assistant"' in app_text:
    sys.exit("STOP: assistant navigation appears to exist already. No files changed.")
footer_anchor = '<footer className="main-footer">'
if app_text.count(footer_anchor) != 1:
    sys.exit("STOP: expected one main footer insertion anchor in App.jsx. No files changed.")
event_anchor = "function EventRow({ event }) {"
if app_text.count(event_anchor) != 1:
    sys.exit("STOP: expected one EventRow component anchor in App.jsx. No files changed.")

# Backend router: use existing `advanced_router` location so app setup order stays explicit.
if "from app.evidence_assistant import router as evidence_assistant_router" in main_text:
    sys.exit("STOP: evidence-assistant router import already exists; inspect integration manually.")
main_fixed = main_text.replace(import_anchor, import_anchor + "\nfrom app.evidence_assistant import router as evidence_assistant_router  # SK_EVIDENCE_ASSISTANT_V1", 1)
if "app.include_router(advanced_router)" in main_fixed:
    main_fixed = main_fixed.replace("app.include_router(advanced_router)", "app.include_router(advanced_router)\napp.include_router(evidence_assistant_router)  # SK_EVIDENCE_ASSISTANT_V1", 1)
else:
    main_fixed = main_fixed.replace("app.include_router(source_router)", "app.include_router(source_router)\napp.include_router(evidence_assistant_router)  # SK_EVIDENCE_ASSISTANT_V1", 1)

# Add the navigation row and render the page. Keep it self-contained so it doesn't disturb existing modules.
nav_block = app_text[nav_start:nav_end]
nav_insert = "  { id: 'assistant', label: 'Evidence assistant', glyph: '✦' },\n"
app_fixed = app_text[:nav_end] + nav_insert + app_text[nav_end:]
app_fixed = app_fixed.replace(
    footer_anchor,
    "{page === 'assistant' && <EvidenceAssistant language={uiLanguage} />}\n\n      " + footer_anchor,
    1,
)

# Update the header subtitle if it contains the known legacy ending; this is optional across UI variants.
legacy_subtitle = ": 'Explore statistical independent components from disease-count signals.'"
if legacy_subtitle in app_fixed:
    app_fixed = app_fixed.replace(
        legacy_subtitle,
        ": page === 'assistant' ? 'Ask questions using the loaded surveillance data and inspect sources.' : 'Explore statistical independent components from disease-count signals.'",
        1,
    )

component = r'''

/* SK_EVIDENCE_ASSISTANT_V1 */
function EvidenceAssistant({ language = 'en' }) {
  const copy = {
    en: { title: 'Evidence assistant', subtitle: 'Ask questions about the loaded surveillance dataset. Answers are retrieved and calculated from structured records, with source links.', placeholder: 'Try “total cases in Karnataka” or “top diseases”…', ask: 'Ask question', busy: 'Searching records…', intro: 'Choose a suggested question or type a question below.', prompts: ['Summarize the surveillance dataset', 'Which diseases have the highest reported cases?', 'Show weekly trend', 'Show cases in Karnataka'], sources: 'Sources', scope: 'Data coverage', error: 'Could not query the evidence assistant.' },
    te: { title: 'సాక్ష్యాధారిత సహాయకుడు', subtitle: 'లోడ్ చేసిన నిఘా డేటాసెట్ గురించి అడగండి. సమాధానాలు నిర్మిత రికార్డుల నుండి లెక్కించబడతాయి; మూల లింకులు చూపబడతాయి.', placeholder: '“total cases in Karnataka” లేదా “top diseases” ప్రయత్నించండి…', ask: 'ప్రశ్న అడగండి', busy: 'రికార్డులు వెతుకుతోంది…', intro: 'సూచించిన ప్రశ్న ఎంచుకోండి లేదా మీ ప్రశ్న టైప్ చేయండి.', prompts: ['నిఘా డేటాసెట్ సారాంశం', 'అత్యధిక కేసులున్న వ్యాధులు', 'వారాల ధోరణి చూపండి', 'Karnataka కేసులు చూపండి'], sources: 'మూలాలు', scope: 'డేటా పరిధి', error: 'సహాయకుడి ప్రశ్నను ప్రాసెస్ చేయలేకపోయింది.' },
    kn: { title: 'ಸಾಕ್ಷ್ಯಾಧಾರಿತ ಸಹಾಯಕ', subtitle: 'ಲೋಡ್ ಮಾಡಿದ ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾಸೆಟ್ ಕುರಿತು ಪ್ರಶ್ನೆ ಕೇಳಿ. ಉತ್ತರಗಳನ್ನು ರಚನಾತ್ಮಕ ದಾಖಲೆಗಳಿಂದ ಲೆಕ್ಕಿಸಲಾಗುತ್ತದೆ; ಮೂಲ ಲಿಂಕ್‌ಗಳೂ ಇರುತ್ತವೆ.', placeholder: '“total cases in Karnataka” ಅಥವಾ “top diseases” ಪ್ರಯತ್ನಿಸಿ…', ask: 'ಪ್ರಶ್ನೆ ಕೇಳಿ', busy: 'ದಾಖಲೆಗಳನ್ನು ಹುಡುಕುತ್ತಿದೆ…', intro: 'ಸೂಚಿಸಿದ ಪ್ರಶ್ನೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ ಅಥವಾ ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಟೈಪ್ ಮಾಡಿ.', prompts: ['ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಸಾರಾಂಶ', 'ಹೆಚ್ಚು ವರದಿಯಾದ ರೋಗಗಳು', 'ವಾರದ ಪ್ರವೃತ್ತಿ ತೋರಿಸಿ', 'Karnataka ಪ್ರಕರಣಗಳನ್ನು ತೋರಿಸಿ'], sources: 'ಮೂಲಗಳು', scope: 'ಡೇಟಾ ವ್ಯಾಪ್ತಿ', error: 'ಸಹಾಯಕವನ್ನು ಪ್ರಶ್ನಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.' },
    hi: { title: 'साक्ष्य-आधारित सहायक', subtitle: 'लोड किए गए निगरानी डेटासेट के बारे में पूछें। उत्तर संरचित रिकॉर्ड से गणना किए जाते हैं और स्रोत लिंक दिखाए जाते हैं।', placeholder: '“total cases in Karnataka” या “top diseases” आज़माएँ…', ask: 'प्रश्न पूछें', busy: 'रिकॉर्ड खोज रहे हैं…', intro: 'सुझाया गया प्रश्न चुनें या अपना प्रश्न लिखें।', prompts: ['निगरानी डेटासेट का सारांश', 'सबसे अधिक रिपोर्ट की गई बीमारियाँ', 'साप्ताहिक रुझान दिखाएँ', 'Karnataka के मामले दिखाएँ'], sources: 'स्रोत', scope: 'डेटा कवरेज', error: 'सहायक से प्रश्न नहीं किया जा सका।' },
  };
  const t = copy[language] || copy.en;
  const [question, setQuestion] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState([]);

  const ask = async (value) => {
    const q = String(value ?? question).trim();
    if (q.length < 3 || q.length > 400 || pending) return;
    setQuestion(q); setPending(true); setError('');
    setHistory((old) => [...old, { role: 'user', text: q }]);
    try {
      const result = await api('/public/assistant/query', {
        method: 'POST',
        body: JSON.stringify({ question: q, language }),
      });
      setHistory((old) => [...old, { role: 'assistant', text: result.answer, sources: result.sources || [], disclaimer: result.disclaimer, items: result.items || [], note: result.note }]);
      setQuestion('');
    } catch (err) {
      setError(err?.message || t.error);
      setHistory((old) => [...old, { role: 'assistant', text: t.error, sources: [], disclaimer: '', items: [] }]);
    } finally { setPending(false); }
  };

  return <>
    <section className="hero-compact sk-evidence-hero"><div><Badge tone="blue">RETRIEVAL-BASED · SOURCE-LINKED</Badge><h2>{t.title}</h2><p>{t.subtitle}</p></div><div className="hero-compact-icon">✦</div></section>
    <section className="panel sk-evidence-panel">
      <div className="panel-heading"><div><span className="eyebrow">PUBLIC HEALTH DATA</span><h3>{t.title}</h3><p className="muted small">{t.intro}</p></div></div>
      <div className="sk-evidence-prompts">{t.prompts.map((prompt) => <button type="button" className="button button-outline" key={prompt} disabled={pending} onClick={() => ask(prompt)}>{prompt}</button>)}</div>
      <form className="sk-evidence-form" onSubmit={(event) => { event.preventDefault(); ask(); }}>
        <textarea value={question} maxLength={400} rows={2} onChange={(event) => setQuestion(event.target.value)} placeholder={t.placeholder} aria-label={t.placeholder} />
        <button className="button button-primary" type="submit" disabled={pending || question.trim().length < 3}>{pending ? t.busy : t.ask}</button>
      </form>
      {error && <div className="alert-banner error-banner"><strong>{t.error}</strong><span>{error}</span></div>}
      <div className="sk-evidence-thread" aria-live="polite">
        {!history.length && <div className="empty-state"><div className="empty-symbol">✦</div><strong>{t.title}</strong><p>{t.intro}</p></div>}
        {history.map((entry, index) => <article className={`sk-evidence-message ${entry.role}`} key={`${entry.role}-${index}`}>
          <div className="sk-evidence-role">{entry.role === 'user' ? 'YOU' : 'EVIDENCE ASSISTANT'}</div>
          <p>{entry.text}</p>
          {entry.items?.length > 0 && entry.items.length < 9 && <div className="sk-evidence-result-grid">{entry.items.map((item, n) => <div className="sk-evidence-result" key={`${item.label || 'summary'}-${n}`}><strong>{item.label || `${item.records} records`}</strong><span>{item.cases} cases · {item.deaths} deaths</span></div>)}</div>}
          {entry.sources?.length > 0 && <div className="sk-evidence-sources"><strong>{t.sources}</strong>{entry.sources.map((source, n) => <div key={`${source.url || source.path}-${n}`}>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url} ↗</a> : <a href={`${API_BASE}${source.path || '/public/surveillance/summary'}`} target="_blank" rel="noreferrer">{source.title || t.sources} ↗</a>}</div>)}</div>}
          {entry.disclaimer && <small className="sk-evidence-disclaimer">{entry.disclaimer}</small>}
        </article>)}
      </div>
      <div className="notice-panel sk-evidence-note"><strong>{t.scope}</strong><p>Answers are computed from structured IDSP records loaded in this installation. This module does not use an LLM, diagnose patients, or declare outbreaks. Always inspect linked source material and the coverage note.</p></div>
    </section>
  </>;
}
'''
app_fixed = app_fixed.replace(event_anchor, component + "\n" + event_anchor, 1)

css_add = r'''

/* SK_EVIDENCE_ASSISTANT_V1 */
.sk-evidence-panel { display: grid; gap: 18px; }
.sk-evidence-prompts { display: flex; flex-wrap: wrap; gap: 9px; }
.sk-evidence-prompts .button { white-space: normal; text-align: left; }
.sk-evidence-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: end; }
.sk-evidence-form textarea { width: 100%; min-height: 56px; resize: vertical; border: 1px solid var(--line, #dbe4ef); border-radius: 12px; padding: 13px 15px; font: inherit; color: inherit; background: var(--panel, #fff); }
.sk-evidence-thread { display: grid; gap: 14px; }
.sk-evidence-message { min-width: 0; max-width: 100%; border: 1px solid var(--line, #dbe4ef); border-radius: 15px; padding: 15px; background: var(--panel, #fff); }
.sk-evidence-message.user { margin-left: auto; width: min(92%, 680px); background: var(--surface-soft, #f4f8ff); }
.sk-evidence-message.assistant { margin-right: auto; width: 100%; }
.sk-evidence-role { font-size: 10px; font-weight: 800; letter-spacing: .12em; color: var(--muted, #607083); }
.sk-evidence-message p { line-height: 1.65; margin: 8px 0; overflow-wrap: anywhere; }
.sk-evidence-result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 9px; margin: 12px 0; }
.sk-evidence-result { display: grid; gap: 5px; padding: 11px; border-radius: 10px; background: var(--surface-soft, #f4f8ff); }
.sk-evidence-result strong { font-size: 13px; }
.sk-evidence-result span { font-size: 12px; color: var(--muted, #607083); }
.sk-evidence-sources { border-top: 1px solid var(--line, #dbe4ef); margin-top: 12px; padding-top: 11px; display: grid; gap: 6px; }
.sk-evidence-sources strong { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
.sk-evidence-sources a { color: var(--accent, #2156a8); overflow-wrap: anywhere; font-size: 13px; }
.sk-evidence-disclaimer { display: block; margin-top: 12px; color: var(--muted, #607083); line-height: 1.5; }
.sk-evidence-note { margin-top: 14px; }
@media (max-width: 720px) { .sk-evidence-form { grid-template-columns: 1fr; } .sk-evidence-form .button { width: 100%; } .sk-evidence-message.user { width: 100%; } }
'''
css_fixed = css_text + css_add

# Add assistant navigation translations when this project has an i18n file.
i18n_fixed = i18n_text
if i18n_fixed is not None:
    replacements = [
        ("ica: 'ICA lab', map: 'Map & hotspots',", "ica: 'ICA lab', map: 'Map & hotspots', assistant: 'Evidence assistant',"),
        ("ica: 'ICA ల్యాబ్', map: 'మ్యాప్ & హాట్‌స్పాట్‌లు',", "ica: 'ICA ల్యాబ్', map: 'మ్యాప్ & హాట్‌స్పాట్‌లు', assistant: 'సాక్ష్యాధారిత సహాయకుడు',"),
        ("ica: 'ICA ಪ್ರಯೋಗಾಲಯ', map: 'ನಕ್ಷೆ ಮತ್ತು ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು',", "ica: 'ICA ಪ್ರಯೋಗಾಲಯ', map: 'ನಕ್ಷೆ ಮತ್ತು ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು', assistant: 'ಸಾಕ್ಷ್ಯಾಧಾರಿತ ಸಹಾಯಕ',"),
        ("ica: 'ICA प्रयोगशाला', map: 'मानचित्र और हॉटस्पॉट',", "ica: 'ICA प्रयोगशाला', map: 'मानचित्र और हॉटस्पॉट', assistant: 'साक्ष्य-आधारित सहायक',"),
    ]
    for old, new in replacements:
        if old in i18n_fixed:
            i18n_fixed = i18n_fixed.replace(old, new, 1)
        # If a language dictionary format changed, existing nav falls back to English without breaking.

# Validate Python route source before modifying the project.
module_text = MODULE_SOURCE.read_text(encoding="utf-8")
compile(module_text, str(MODULE_SOURCE), "exec")
test_text = TEST_SOURCE.read_text(encoding="utf-8")
compile(test_text, str(TEST_SOURCE), "exec")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / "backups" / f"evidence_assistant_{stamp}"
backup_dir.mkdir(parents=True, exist_ok=False)
for path in (MAIN, APP, CSS):
    shutil.copy2(path, backup_dir / f"{path.name}.bak")
if I18N.exists():
    shutil.copy2(I18N, backup_dir / "i18n.js.bak")

MAIN.write_text(main_fixed, encoding="utf-8", newline="")
APP.write_text(app_fixed, encoding="utf-8", newline="")
CSS.write_text(css_fixed, encoding="utf-8", newline="")
(ROOT / "backend" / "app" / "evidence_assistant.py").write_text(module_text, encoding="utf-8", newline="")
(ROOT / "backend" / "tests" / "test_evidence_assistant.py").write_text(test_text, encoding="utf-8", newline="")
doc_path = ROOT / "docs" / "evidence-assistant.md"
doc_path.parent.mkdir(parents=True, exist_ok=True)
doc_path.write_text(DOC_SOURCE.read_text(encoding="utf-8"), encoding="utf-8", newline="")
if i18n_fixed is not None:
    I18N.write_text(i18n_fixed, encoding="utf-8", newline="")

print("Evidence Assistant installed.")
print("Endpoint: POST /public/assistant/query")
print("Answers are retrieved/aggregated from IDSP database rows and include sources/disclaimer.")
print("This is not an LLM chatbot or a clinical/outbreak-declaration system.")
print("Backup:", backup_dir)
