import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  DEFAULT_API_BASE_URL,
  buildAssistantRequest,
  normalizeApiBase,
  parseSourceStatus,
  parseSummary,
  requestJSON,
} from './src/api.mjs';

const API_BASE = normalizeApiBase(process.env.EXPO_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL);
const LANGS = [
  { code: 'en', label: 'English' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'kn', label: 'ಕನ್ನಡ' },
  { code: 'hi', label: 'हिन्दी' },
];

const COPY = {
  en: { overview: 'Overview', evidence: 'Evidence', sources: 'Sources', appTitle: 'Samraksha Kendra', eyebrow: 'PUBLIC HEALTH INTELLIGENCE', summary: 'Surveillance at a glance', totalRecords: 'Records', cases: 'Reported cases', deaths: 'Reported deaths', states: 'States / UTs', diseases: 'Disease labels', hospitals: 'Hospital directory', refresh: 'Refresh data', available: 'Available', unavailable: 'Unavailable', loading: 'Loading data…', offline: 'Could not load the API. Check your connection and retry.', noSources: 'No source status returned yet.', askTitle: 'Ask the evidence assistant', prompt: 'Ask about the loaded surveillance data…', send: 'Ask', asking: 'Checking data…', prompts: ['Summarize the surveillance dataset', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'Sources', disclaimer: 'Coverage note: answers reflect only records loaded in this installation. Not medical advice or an official outbreak declaration.', sourceWarning: 'Publication notices are not a continuous case-count feed.', emptyAnswer: 'Ask a question to get a source-grounded answer.', error: 'Something went wrong. Please retry.', recordsLine: 'records', casesLine: 'cases', deathsLine: 'deaths' },
  te: { overview: 'సారాంశం', evidence: 'ఆధారాలు', sources: 'మూలాలు', appTitle: 'సంరక్ష కేంద్రం', eyebrow: 'ప్రజారోగ్య సమాచార వేదిక', summary: 'నిఘా సంక్షిప్త వివరాలు', totalRecords: 'రికార్డులు', cases: 'నివేదించిన కేసులు', deaths: 'నివేదించిన మరణాలు', states: 'రాష్ట్రాలు / UTలు', diseases: 'వ్యాధి పేర్లు', hospitals: 'ఆసుపత్రుల డైరెక్టరీ', refresh: 'డేటా రిఫ్రెష్', available: 'అందుబాటులో ఉంది', unavailable: 'అందుబాటులో లేదు', loading: 'డేటా లోడ్ అవుతోంది…', offline: 'API డేటా లోడ్ కాలేదు. కనెక్షన్ తనిఖీ చేసి మళ్లీ ప్రయత్నించండి.', noSources: 'మూలాల స్థితి ఇంకా అందుబాటులో లేదు.', askTitle: 'ఆధారాల సహాయకుడిని అడగండి', prompt: 'లోడ్ చేసిన నిఘా డేటా గురించి అడగండి…', send: 'అడగండి', asking: 'డేటా పరిశీలిస్తోంది…', prompts: ['నిఘా డేటా సారాంశం', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'మూలాలు', disclaimer: 'గమనిక: సమాధానాలు ఈ వ్యవస్థలో లోడ్ చేసిన రికార్డులకే పరిమితం. వైద్య సలహా లేదా అధికారిక ప్రకటన కాదు.', sourceWarning: 'ప్రచురణ నోటీసులు నిరంతర కేసుల ఫీడ్ కావు.', emptyAnswer: 'ఆధారాలతో సమాధానం పొందేందుకు ప్రశ్న అడగండి.', error: 'సమస్య ఏర్పడింది. మళ్లీ ప్రయత్నించండి.', recordsLine: 'రికార్డులు', casesLine: 'కేసులు', deathsLine: 'మరణాలు' },
  kn: { overview: 'ಅವಲೋಕನ', evidence: 'ಆಧಾರ', sources: 'ಮೂಲಗಳು', appTitle: 'ಸಂರಕ್ಷ ಕೇಂದ್ರ', eyebrow: 'ಸಾರ್ವಜನಿಕ ಆರೋಗ್ಯ ಮಾಹಿತಿ', summary: 'ಒಂದು ನೋಟದಲ್ಲಿ ಮೇಲ್ವಿಚಾರಣೆ', totalRecords: 'ದಾಖಲೆಗಳು', cases: 'ವರದಿಯಾದ ಪ್ರಕರಣಗಳು', deaths: 'ವರದಿಯಾದ ಸಾವುಗಳು', states: 'ರಾಜ್ಯಗಳು / UTಗಳು', diseases: 'ರೋಗದ ಹೆಸರುಗಳು', hospitals: 'ಆಸ್ಪತ್ರೆ ಡೈರೆಕ್ಟರಿ', refresh: 'ಡೇಟಾ ರಿಫ್ರೆಶ್', available: 'ಲಭ್ಯವಿದೆ', unavailable: 'ಲಭ್ಯವಿಲ್ಲ', loading: 'ಡೇಟಾ ಲೋಡ್ ಆಗುತ್ತಿದೆ…', offline: 'API ಲೋಡ್ ಆಗಲಿಲ್ಲ. ಸಂಪರ್ಕ ಪರಿಶೀಲಿಸಿ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.', noSources: 'ಮೂಲ ಸ್ಥಿತಿ ಇನ್ನೂ ಲಭ್ಯವಿಲ್ಲ.', askTitle: 'ಸಾಕ್ಷ್ಯ ಸಹಾಯಕನನ್ನು ಕೇಳಿ', prompt: 'ಲೋಡ್ ಮಾಡಿದ ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಬಗ್ಗೆ ಕೇಳಿ…', send: 'ಕೇಳಿ', asking: 'ಡೇಟಾ ಪರಿಶೀಲಿಸುತ್ತಿದೆ…', prompts: ['ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಸಾರಾಂಶ', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'ಮೂಲಗಳು', disclaimer: 'ಗಮನಿಸಿ: ಉತ್ತರಗಳು ಈ ವ್ಯವಸ್ಥೆಯಲ್ಲಿ ಲೋಡ್ ಮಾಡಿದ ದಾಖಲೆಗಳಿಗೆ ಮಾತ್ರ ಸೀಮಿತ. ವೈದ್ಯಕೀಯ ಸಲಹೆ ಅಥವಾ ಅಧಿಕೃತ ಘೋಷಣೆ ಅಲ್ಲ.', sourceWarning: 'ಪ್ರಕಟಣೆ ಸೂಚನೆಗಳು ನಿರಂತರ ಪ್ರಕರಣಗಳ ಫೀಡ್ ಅಲ್ಲ.', emptyAnswer: 'ಮೂಲಾಧಾರಿತ ಉತ್ತರಕ್ಕಾಗಿ ಪ್ರಶ್ನೆ ಕೇಳಿ.', error: 'ದೋಷ ಸಂಭವಿಸಿದೆ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.', recordsLine: 'ದಾಖಲೆಗಳು', casesLine: 'ಪ್ರಕರಣಗಳು', deathsLine: 'ಸಾವುಗಳು' },
  hi: { overview: 'अवलोकन', evidence: 'साक्ष्य', sources: 'स्रोत', appTitle: 'संरक्षा केंद्र', eyebrow: 'सार्वजनिक स्वास्थ्य जानकारी', summary: 'निगरानी एक नज़र में', totalRecords: 'रिकॉर्ड', cases: 'रिपोर्ट किए गए मामले', deaths: 'रिपोर्ट की गई मौतें', states: 'राज्य / केंद्र शासित प्रदेश', diseases: 'बीमारी लेबल', hospitals: 'अस्पताल निर्देशिका', refresh: 'डेटा रीफ़्रेश', available: 'उपलब्ध', unavailable: 'अनुपलब्ध', loading: 'डेटा लोड हो रहा है…', offline: 'API डेटा लोड नहीं हुआ। कनेक्शन जाँचकर पुनः प्रयास करें।', noSources: 'स्रोत स्थिति अभी उपलब्ध नहीं है।', askTitle: 'साक्ष्य सहायक से पूछें', prompt: 'लोड किए गए निगरानी डेटा के बारे में पूछें…', send: 'पूछें', asking: 'डेटा जाँचा जा रहा है…', prompts: ['निगरानी डेटासेट का सारांश', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'स्रोत', disclaimer: 'ध्यान दें: उत्तर केवल इस स्थापना में लोड रिकॉर्ड तक सीमित हैं। यह चिकित्सकीय सलाह या आधिकारिक प्रकोप घोषणा नहीं है।', sourceWarning: 'प्रकाशन सूचनाएँ निरंतर केस-काउंट फ़ीड नहीं हैं।', emptyAnswer: 'स्रोत-आधारित उत्तर के लिए प्रश्न पूछें।', error: 'समस्या हुई। कृपया फिर प्रयास करें।', recordsLine: 'रिकॉर्ड', casesLine: 'मामले', deathsLine: 'मौतें' },
};

const fmt = (value) => Number(value ?? 0).toLocaleString('en-IN');

function ActionButton({ children, onPress, disabled, secondary = false, accessibilityLabel }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel || String(children)} onPress={onPress} disabled={disabled} style={({ pressed }) => [styles.button, secondary && styles.buttonSecondary, disabled && styles.buttonDisabled, pressed && !disabled && styles.buttonPressed]}><Text style={[styles.buttonText, secondary && styles.buttonTextSecondary]}>{children}</Text></Pressable>;
}

function StatCard({ label, value, accent = false }) {
  return <View style={[styles.statCard, accent && styles.statCardAccent]}><Text style={[styles.statLabel, accent && styles.statLabelAccent]}>{label}</Text><Text accessibilityRole="text" style={[styles.statValue, accent && styles.statValueAccent]}>{fmt(value)}</Text></View>;
}

export default function App() {
  const [tab, setTab] = useState('overview');
  const [language, setLanguage] = useState('en');
  const [summary, setSummary] = useState(null);
  const [hospitalCount, setHospitalCount] = useState(0);
  const [sources, setSources] = useState([]);
  const [busy, setBusy] = useState(false);
  const [pageError, setPageError] = useState('');
  const [question, setQuestion] = useState('');
  const [answerBusy, setAnswerBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [answerError, setAnswerError] = useState('');
  const t = COPY[language] || COPY.en;

  const refreshData = useCallback(async () => {
    setBusy(true);
    setPageError('');
    try {
      const [summaryData, hospitalData, sourceData] = await Promise.all([
        requestJSON('/public/surveillance/summary', {}, fetch, API_BASE),
        requestJSON('/hospitals/count', {}, fetch, API_BASE).catch(() => ({ count: 0 })),
        requestJSON('/system/source-status', {}, fetch, API_BASE).catch(() => ({ sources: [] })),
      ]);
      setSummary(parseSummary(summaryData));
      setHospitalCount(Number(hospitalData.count ?? hospitalData.total ?? 0) || 0);
      setSources(parseSourceStatus(sourceData));
    } catch (error) {
      setPageError(error?.message || t.offline);
    } finally {
      setBusy(false);
    }
  }, [t.offline]);

  useEffect(() => { refreshData(); }, [refreshData]);

  const ask = useCallback(async (value = question) => {
    let body;
    try { body = buildAssistantRequest(value, language); }
    catch (error) { setAnswerError(error.message); return; }
    setQuestion(body.question);
    setAnswerError('');
    setAnswerBusy(true);
    try {
      const result = await requestJSON('/public/assistant/query', { method: 'POST', body }, fetch, API_BASE);
      setAnswer(result);
    } catch (error) {
      setAnswerError(error?.message || t.error);
    } finally {
      setAnswerBusy(false);
    }
  }, [question, language, t.error]);

  const pickPrompt = (prompt) => {
    setQuestion(prompt);
    ask(prompt);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" backgroundColor={COLORS.navy} />
      <View style={styles.header}>
        <View style={styles.brandRow}>
          <View style={styles.logo}><Text style={styles.logoText}>SK</Text></View>
          <View style={styles.brandCopy}><Text style={styles.eyebrow}>{t.eyebrow}</Text><Text style={styles.brandTitle}>{t.appTitle}</Text></View>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.languageRow}>
          {LANGS.map((item) => <Pressable key={item.code} accessibilityRole="button" onPress={() => setLanguage(item.code)} style={[styles.languageChip, language === item.code && styles.languageChipActive]}><Text style={[styles.languageText, language === item.code && styles.languageTextActive]}>{item.label}</Text></Pressable>)}
        </ScrollView>
      </View>

      <View style={styles.tabs}>
        {[['overview', t.overview], ['evidence', t.evidence], ['sources', t.sources]].map(([id, label]) => <Pressable key={id} accessibilityRole="tab" accessibilityState={{ selected: tab === id }} onPress={() => setTab(id)} style={[styles.tab, tab === id && styles.tabActive]}><Text style={[styles.tabText, tab === id && styles.tabTextActive]}>{label}</Text></Pressable>)}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={tab === 'overview' ? <RefreshControl refreshing={busy} onRefresh={refreshData} tintColor={COLORS.teal} /> : undefined}
        keyboardShouldPersistTaps="handled"
      >
        {tab === 'overview' && <>
          <View style={styles.sectionHeader}><View><Text style={styles.sectionKicker}>SURVEILLANCE WORKSPACE</Text><Text style={styles.sectionTitle}>{t.summary}</Text></View><ActionButton secondary onPress={refreshData} disabled={busy}>{busy ? '…' : t.refresh}</ActionButton></View>
          {!!pageError && <View style={styles.errorBox}><Text style={styles.errorText}>{pageError}</Text><ActionButton onPress={refreshData}>{t.refresh}</ActionButton></View>}
          {busy && !summary ? <View style={styles.loading}><ActivityIndicator size="large" color={COLORS.teal} /><Text style={styles.muted}>{t.loading}</Text></View> : summary ? <>
            <View style={styles.statsGrid}>
              <StatCard label={t.totalRecords} value={summary.records} accent />
              <StatCard label={t.cases} value={summary.cases} />
              <StatCard label={t.deaths} value={summary.deaths} />
              <StatCard label={t.states} value={summary.states} />
              <StatCard label={t.diseases} value={summary.diseases} />
              <StatCard label={t.hospitals} value={hospitalCount} />
            </View>
            <View style={styles.noteCard}><Text style={styles.noteTitle}>DATA COVERAGE</Text><Text style={styles.noteText}>{t.disclaimer}</Text></View>
          </> : null}
        </>}

        {tab === 'evidence' && <>
          <Text style={styles.sectionKicker}>PUBLIC HEALTH DATA</Text>
          <Text style={styles.sectionTitle}>{t.askTitle}</Text>
          <Text style={styles.bodyCopy}>{t.disclaimer}</Text>
          <View style={styles.promptList}>{t.prompts.map((prompt) => <Pressable key={prompt} onPress={() => pickPrompt(prompt)} style={styles.promptChip}><Text style={styles.promptText}>{prompt}</Text></Pressable>)}</View>
          <TextInput
            accessibilityLabel={t.prompt}
            value={question}
            onChangeText={setQuestion}
            onSubmitEditing={() => ask()}
            placeholder={t.prompt}
            placeholderTextColor={COLORS.muted}
            returnKeyType="send"
            blurOnSubmit
            maxLength={400}
            multiline={false}
            style={styles.input}
          />
          <ActionButton onPress={() => ask()} disabled={answerBusy || question.trim().length < 1}>{answerBusy ? t.asking : t.send}</ActionButton>
          {!!answerError && <Text style={styles.errorText}>{answerError}</Text>}
          {answer && <View style={styles.answerCard}>
            <Text style={styles.answerKicker}>EVIDENCE ASSISTANT · {String(answer.status || 'answered').toUpperCase()}</Text>
            <Text style={styles.answerText}>{answer.answer}</Text>
            {Array.isArray(answer.items) && answer.items.length > 0 && <View style={styles.answerMetrics}>{answer.items.slice(0, 5).map((item, index) => <View key={`${item.label || 'result'}-${index}`} style={styles.answerMetric}><Text style={styles.answerMetricTitle}>{item.label || `${fmt(item.records)} ${t.recordsLine}`}</Text><Text style={styles.muted}>{fmt(item.cases)} {t.casesLine} · {fmt(item.deaths)} {t.deathsLine}</Text></View>)}</View>}
            <Text style={styles.sourceHeader}>{t.sourcesForAnswer}</Text>
            {(answer.sources || []).map((source, index) => {
              const url = source.url || (source.path ? `${API_BASE}${source.path}` : `${API_BASE}/public/surveillance/summary`);
              return <Pressable key={`${url}-${index}`} onPress={() => Linking.openURL(url).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>{source.title || url} ↗</Text></Pressable>;
            })}
            <Text style={styles.noteText}>{answer.disclaimer || t.disclaimer}</Text>
          </View>}
        </>}

        {tab === 'sources' && <>
          <Text style={styles.sectionKicker}>OFFICIAL SOURCE UPDATES</Text>
          <Text style={styles.sectionTitle}>{t.sources}</Text>
          <ActionButton secondary onPress={refreshData} disabled={busy}>{busy ? '…' : t.refresh}</ActionButton>
          {sources.length === 0 && <Text style={styles.muted}>{t.noSources}</Text>}
          {sources.map((source, index) => <View key={`${source.name}-${index}`} style={styles.sourceCard}>
            <View style={styles.sourceTop}><Text style={styles.sourceName}>{source.name}</Text><View style={[styles.statusBadge, source.status === 'available' ? styles.statusAvailable : styles.statusUnavailable]}><Text style={styles.statusText}>{source.status === 'available' ? t.available : t.unavailable}</Text></View></View>
            <Text style={styles.muted}>Items available: {fmt(source.items_available)}</Text>
            {!!source.warning && <Text style={styles.noteText}>{source.warning}</Text>}
            {!!source.source_url && <Pressable onPress={() => Linking.openURL(source.source_url).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open official source ↗</Text></Pressable>}
          </View>)}
        </>}

        <View style={styles.footer}><Text style={styles.footerText}>Samraksha Kendra · Research prototype</Text><Text style={styles.footerText}>Not a medical advice or official outbreak declaration service.</Text></View>
      </ScrollView>
    </SafeAreaView>
  );
}

const COLORS = {
  navy: '#0B1830', navy2: '#132642', teal: '#23B7A4', tealDark: '#087F73', text: '#162338', muted: '#68778D', page: '#F3F6FA', card: '#FFFFFF', border: '#E0E7F0', pale: '#E8F8F5', redPale: '#FFF0EC', red: '#B6402C', greenPale: '#E5F8F0', green: '#13754F',
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.page },
  header: { backgroundColor: COLORS.navy, paddingHorizontal: 18, paddingTop: 10, paddingBottom: 14 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logo: { width: 46, height: 46, borderRadius: 14, backgroundColor: COLORS.teal, alignItems: 'center', justifyContent: 'center' },
  logoText: { color: COLORS.navy, fontWeight: '900', fontSize: 17, letterSpacing: 1 },
  brandCopy: { flex: 1 },
  eyebrow: { color: '#9CB1CA', fontSize: 9, letterSpacing: 1.5, fontWeight: '800' },
  brandTitle: { color: '#FFFFFF', fontSize: 22, fontWeight: '800', marginTop: 2 },
  languageRow: { gap: 8, paddingTop: 14 },
  languageChip: { borderWidth: 1, borderColor: '#334762', borderRadius: 99, paddingHorizontal: 11, paddingVertical: 7 },
  languageChipActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  languageText: { fontSize: 11, color: '#D8E2EE', fontWeight: '700' },
  languageTextActive: { color: COLORS.navy },
  tabs: { flexDirection: 'row', backgroundColor: '#FFFFFF', paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  tab: { flex: 1, paddingVertical: 14, alignItems: 'center', borderBottomWidth: 3, borderBottomColor: 'transparent' },
  tabActive: { borderBottomColor: COLORS.teal },
  tabText: { color: COLORS.muted, fontWeight: '700', fontSize: 12 },
  tabTextActive: { color: COLORS.tealDark },
  content: { padding: 16, paddingBottom: 32, gap: 14 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  sectionKicker: { color: COLORS.tealDark, fontWeight: '800', letterSpacing: 1.2, fontSize: 9, marginBottom: 5 },
  sectionTitle: { color: COLORS.text, fontWeight: '900', fontSize: 23, marginBottom: 6 },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  statCard: { width: '48%', flexGrow: 1, minWidth: 135, backgroundColor: COLORS.card, padding: 15, borderRadius: 15, borderWidth: 1, borderColor: COLORS.border, minHeight: 98, justifyContent: 'space-between' },
  statCardAccent: { backgroundColor: COLORS.navy, borderColor: COLORS.navy },
  statLabel: { color: COLORS.muted, fontSize: 12, fontWeight: '700' },
  statLabelAccent: { color: '#B9CADC' },
  statValue: { color: COLORS.text, fontSize: 26, fontWeight: '900', marginTop: 11 },
  statValueAccent: { color: '#FFFFFF' },
  button: { backgroundColor: COLORS.tealDark, paddingVertical: 12, paddingHorizontal: 16, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  buttonSecondary: { backgroundColor: '#FFFFFF', borderColor: COLORS.border, borderWidth: 1 },
  buttonDisabled: { opacity: 0.55 },
  buttonPressed: { opacity: 0.82 },
  buttonText: { color: '#FFFFFF', fontWeight: '800', fontSize: 13 },
  buttonTextSecondary: { color: COLORS.text },
  noteCard: { backgroundColor: COLORS.pale, borderRadius: 13, padding: 14, gap: 7 },
  noteTitle: { color: COLORS.tealDark, fontSize: 10, letterSpacing: 1.1, fontWeight: '900' },
  noteText: { color: COLORS.muted, fontSize: 12, lineHeight: 18, marginTop: 7 },
  loading: { minHeight: 150, alignItems: 'center', justifyContent: 'center', gap: 12 },
  muted: { color: COLORS.muted, fontSize: 12, lineHeight: 18 },
  errorBox: { padding: 14, gap: 10, backgroundColor: COLORS.redPale, borderRadius: 12 },
  errorText: { color: COLORS.red, fontSize: 12, lineHeight: 18 },
  bodyCopy: { color: COLORS.muted, fontSize: 12, lineHeight: 19, marginBottom: 4 },
  promptList: { gap: 8 },
  promptChip: { alignSelf: 'flex-start', borderRadius: 99, borderColor: COLORS.border, borderWidth: 1, backgroundColor: '#FFFFFF', paddingHorizontal: 12, paddingVertical: 9, maxWidth: '100%' },
  promptText: { color: COLORS.text, fontSize: 12, fontWeight: '700' },
  input: { minHeight: 52, backgroundColor: '#FFFFFF', borderRadius: 12, paddingHorizontal: 14, paddingVertical: 13, borderColor: COLORS.border, borderWidth: 1, color: COLORS.text, fontSize: 14 },
  answerCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 16, padding: 15, gap: 7 },
  answerKicker: { color: COLORS.tealDark, fontSize: 9, fontWeight: '900', letterSpacing: 1.1 },
  answerText: { color: COLORS.text, fontSize: 14, lineHeight: 21, marginVertical: 4 },
  answerMetrics: { gap: 8, marginVertical: 7 },
  answerMetric: { borderRadius: 10, backgroundColor: COLORS.page, padding: 11, gap: 4 },
  answerMetricTitle: { color: COLORS.text, fontSize: 12, fontWeight: '800' },
  sourceHeader: { color: COLORS.text, fontWeight: '900', fontSize: 10, letterSpacing: 1, marginTop: 8 },
  sourceLink: { paddingVertical: 7 },
  sourceLinkText: { color: COLORS.tealDark, fontSize: 12, fontWeight: '700' },
  sourceCard: { backgroundColor: '#FFFFFF', borderColor: COLORS.border, borderWidth: 1, borderRadius: 14, padding: 14, gap: 7 },
  sourceTop: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 },
  sourceName: { flex: 1, color: COLORS.text, fontWeight: '800', fontSize: 14, lineHeight: 20 },
  statusBadge: { borderRadius: 99, paddingVertical: 4, paddingHorizontal: 8 },
  statusAvailable: { backgroundColor: COLORS.greenPale },
  statusUnavailable: { backgroundColor: COLORS.redPale },
  statusText: { color: COLORS.green, fontSize: 10, fontWeight: '800' },
  footer: { marginTop: 18, paddingTop: 15, borderTopWidth: 1, borderTopColor: COLORS.border, gap: 3 },
  footerText: { fontSize: 10, color: '#8290A2', lineHeight: 15 },
});
