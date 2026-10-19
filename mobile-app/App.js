import React, { useCallback, useEffect, useState } from 'react';
import { AppState, Alert } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import * as SecureStore from 'expo-secure-store';
import Svg, { Path } from 'react-native-svg';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  DEFAULT_API_BASE_URL,
  buildAssistantRequest,
  normalizeApiBase,
  parseSourceStatus,
  parseSummary,
  requestJSON,
  extractAccessToken,
} from './src/api.mjs';
import { aggregateDistrictTrends, filterTrendRecords, getDistrictReportDetails } from './src/trends.mjs';
import { compactPeriodLabel, displayStatValue, prepareIcaSignalData, prepareRankingBars, prepareWeeklyChartPoints, safePageLabel } from './src/mobileVisuals.mjs';
import { buildReviewerDecision, colorForMapState, normalizeReviewerQueue, normalizeStateKey, normalizeStagingSummary, summarizeLatestStateReports } from './src/mobileFullParity.mjs';
import { INDIA_STATE_PATHS } from './src/indiaStatePaths.mjs';
import { buildHistoryQuery, apiToWebSocketUrl, isSessionRejectedMessage, SNAPSHOT_REFRESH_MS, OFFICIAL_FEED_REFRESH_MS, SOCKET_HEARTBEAT_MS, SOCKET_RETRY_MS, normalizePagedRecords } from './src/mobileParity.mjs';

const API_BASE = normalizeApiBase(process.env.EXPO_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL);
const SESSION_TOKEN_KEY = 'samraksha_kendra_access_token_v1';
const LANGS = [
  { code: 'en', label: 'English' },
  { code: 'te', label: '\u0C24\u0C46\u0C32\u0C41\u0C17\u0C41' },
  { code: 'kn', label: '\u0C95\u0CA8\u0CCD\u0CA8\u0C21' },
  { code: 'hi', label: '\u0939\u093F\u0928\u094D\u0926\u0940' },
];

const COPY = {
  en: { overview: 'Overview', evidence: 'Evidence', sources: 'Sources', appTitle: 'Samraksha Kendra', eyebrow: 'PUBLIC HEALTH INTELLIGENCE', summary: 'Surveillance at a glance', totalRecords: 'Records', cases: 'Reported cases', deaths: 'Reported deaths', states: 'States / UTs', diseases: 'Disease labels', hospitals: 'Hospital directory', refresh: 'Refresh data', available: 'Available', unavailable: 'Unavailable', loading: 'Loading data…', offline: 'Could not load the API. Check your connection and retry.', noSources: 'No source status returned yet.', askTitle: 'Ask the evidence assistant', prompt: 'Ask about the loaded surveillance data…', send: 'Ask', asking: 'Checking data…', prompts: ['Summarize the surveillance dataset', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'Sources', disclaimer: 'Coverage note: answers reflect only records loaded in this installation. Not medical advice or an official outbreak declaration.', sourceWarning: 'Publication notices are not a continuous case-count feed.', emptyAnswer: 'Ask a question to get a source-grounded answer.', error: 'Something went wrong. Please retry.', trends: 'Trends', trendTitle: 'District outbreak trends', trendHint: 'Explore the available IDSP reports. Filters apply to the records returned by the API.', diseaseFilter: 'Filter disease', stateFilter: 'Filter state', dateFrom: 'From date (YYYY-MM-DD)', dateTo: 'To date (YYYY-MM-DD)', refreshTrends: 'Refresh reports', clearFilters: 'Clear filters', recordsFound: 'Matching records', topDistricts: 'Districts with most reported cases', noTrendRecords: 'No records match these filters.', latestReport: 'Latest report', trendCoverage: 'Coverage note: rankings reflect only available reports, up to 500 records returned by the API. They are not a live or official outbreak declaration.', recordsLine: 'records', casesLine: 'cases', deathsLine: 'deaths' },
  te: { overview: 'సారాంశం', evidence: 'ఆధారాలు', sources: 'మూలాలు', appTitle: 'సంరక్ష కేంద్రం', eyebrow: 'ప్రజారోగ్య సమాచార వేదిక', summary: 'నిఘా సంక్షిప్త వివరాలు', totalRecords: 'రికార్డులు', cases: 'నివేదించిన కేసులు', deaths: 'నివేదించిన మరణాలు', states: 'రాష్ట్రాలు / UTలు', diseases: 'వ్యాధి పేర్లు', hospitals: 'ఆసుపత్రుల డైరెక్టరీ', refresh: 'డేటా రిఫ్రెష్', available: 'అందుబాటులో ఉంది', unavailable: 'అందుబాటులో లేదు', loading: 'డేటా లోడ్ అవుతోంది…', offline: 'API డేటా లోడ్ కాలేదు. కనెక్షన్ తనిఖీ చేసి మళ్లీ ప్రయత్నించండి.', noSources: 'మూలాల స్థితి ఇంకా అందుబాటులో లేదు.', askTitle: 'ఆధారాల సహాయకుడిని అడగండి', prompt: 'లోడ్ చేసిన నిఘా డేటా గురించి అడగండి…', send: 'అడగండి', asking: 'డేటా పరిశీలిస్తోంది…', prompts: ['నిఘా డేటా సారాంశం', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'మూలాలు', disclaimer: 'గమనిక: సమాధానాలు ఈ వ్యవస్థలో లోడ్ చేసిన రికార్డులకే పరిమితం. వైద్య సలహా లేదా అధికారిక ప్రకటన కాదు.', sourceWarning: 'ప్రచురణ నోటీసులు నిరంతర కేసుల ఫీడ్ కావు.', emptyAnswer: 'ఆధారాలతో సమాధానం పొందేందుకు ప్రశ్న అడగండి.', error: 'సమస్య ఏర్పడింది. మళ్లీ ప్రయత్నించండి.', trends: 'ధోరణులు', trendTitle: 'జిల్లాల వ్యాప్తి ధోరణులు', trendHint: 'అందుబాటులో ఉన్న IDSP నివేదికలను పరిశీలించండి. ఫిల్టర్లు API అందించిన రికార్డులపై వర్తిస్తాయి.', diseaseFilter: 'వ్యాధి ఫిల్టర్', stateFilter: 'రాష్ట్ర ఫిల్టర్', dateFrom: 'తేదీ నుంచి (YYYY-MM-DD)', dateTo: 'తేదీ వరకు (YYYY-MM-DD)', refreshTrends: 'నివేదికలను రిఫ్రెష్ చేయండి', clearFilters: 'ఫిల్టర్లు తొలగించండి', recordsFound: 'సరిపోలిన రికార్డులు', topDistricts: 'ఎక్కువగా నివేదించిన కేసుల జిల్లాలు', noTrendRecords: 'ఈ ఫిల్టర్లకు రికార్డులు లేవు.', latestReport: 'చివరి నివేదిక', trendCoverage: 'గమనిక: ర్యాంకింగ్ API ఇచ్చిన గరిష్ఠంగా 500 అందుబాటులో ఉన్న నివేదికలపైనే ఆధారపడుతుంది. ఇది ప్రత్యక్ష లేదా అధికారిక వ్యాప్తి ప్రకటన కాదు.', recordsLine: 'రికార్డులు', casesLine: 'కేసులు', deathsLine: 'మరణాలు' },
  kn: { overview: 'ಅವಲೋಕನ', evidence: 'ಆಧಾರ', sources: 'ಮೂಲಗಳು', appTitle: 'ಸಂರಕ್ಷ ಕೇಂದ್ರ', eyebrow: 'ಸಾರ್ವಜನಿಕ ಆರೋಗ್ಯ ಮಾಹಿತಿ', summary: 'ಒಂದು ನೋಟದಲ್ಲಿ ಮೇಲ್ವಿಚಾರಣೆ', totalRecords: 'ದಾಖಲೆಗಳು', cases: 'ವರದಿಯಾದ ಪ್ರಕರಣಗಳು', deaths: 'ವರದಿಯಾದ ಸಾವುಗಳು', states: 'ರಾಜ್ಯಗಳು / UTಗಳು', diseases: 'ರೋಗದ ಹೆಸರುಗಳು', hospitals: 'ಆಸ್ಪತ್ರೆ ಡೈರೆಕ್ಟರಿ', refresh: 'ಡೇಟಾ ರಿಫ್ರೆಶ್', available: 'ಲಭ್ಯವಿದೆ', unavailable: 'ಲಭ್ಯವಿಲ್ಲ', loading: 'ಡೇಟಾ ಲೋಡ್ ಆಗುತ್ತಿದೆ…', offline: 'API ಲೋಡ್ ಆಗಲಿಲ್ಲ. ಸಂಪರ್ಕ ಪರಿಶೀಲಿಸಿ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.', noSources: 'ಮೂಲ ಸ್ಥಿತಿ ಇನ್ನೂ ಲಭ್ಯವಿಲ್ಲ.', askTitle: 'ಸಾಕ್ಷ್ಯ ಸಹಾಯಕನನ್ನು ಕೇಳಿ', prompt: 'ಲೋಡ್ ಮಾಡಿದ ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಬಗ್ಗೆ ಕೇಳಿ…', send: 'ಕೇಳಿ', asking: 'ಡೇಟಾ ಪರಿಶೀಲಿಸುತ್ತಿದೆ…', prompts: ['ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಸಾರಾಂಶ', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'ಮೂಲಗಳು', disclaimer: 'ಗಮನಿಸಿ: ಉತ್ತರಗಳು ಈ ವ್ಯವಸ್ಥೆಯಲ್ಲಿ ಲೋಡ್ ಮಾಡಿದ ದಾಖಲೆಗಳಿಗೆ ಮಾತ್ರ ಸೀಮಿತ. ವೈದ್ಯಕೀಯ ಸಲಹೆ ಅಥವಾ ಅಧಿಕೃತ ಘೋಷಣೆ ಅಲ್ಲ.', sourceWarning: 'ಪ್ರಕಟಣೆ ಸೂಚನೆಗಳು ನಿರಂತರ ಪ್ರಕರಣಗಳ ಫೀಡ್ ಅಲ್ಲ.', emptyAnswer: 'ಮೂಲಾಧಾರಿತ ಉತ್ತರಕ್ಕಾಗಿ ಪ್ರಶ್ನೆ ಕೇಳಿ.', error: 'ದೋಷ ಸಂಭವಿಸಿದೆ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.', trends: 'ಪ್ರವೃತ್ತಿಗಳು', trendTitle: 'ಜಿಲ್ಲಾವಾರು ರೋಗ ಹರಡುವಿಕೆಯ ಪ್ರವೃತ್ತಿ', trendHint: 'ಲಭ್ಯವಿರುವ IDSP ವರದಿಗಳನ್ನು ವೀಕ್ಷಿಸಿ. ಫಿಲ್ಟರ್‌ಗಳು API ಹಿಂತಿರುಗಿಸಿದ ದಾಖಲೆಗಳಿಗೆ ಅನ್ವಯಿಸುತ್ತವೆ.', diseaseFilter: 'ರೋಗ ಫಿಲ್ಟರ್', stateFilter: 'ರಾಜ್ಯ ಫಿಲ್ಟರ್', dateFrom: 'ದಿನಾಂಕದಿಂದ (YYYY-MM-DD)', dateTo: 'ದಿನಾಂಕದವರೆಗೆ (YYYY-MM-DD)', refreshTrends: 'ವರದಿಗಳನ್ನು ರಿಫ್ರೆಶ್ ಮಾಡಿ', clearFilters: 'ಫಿಲ್ಟರ್ ತೆರವುಗೊಳಿಸಿ', recordsFound: 'ಹೊಂದಾಣಿಕೆಯ ದಾಖಲೆಗಳು', topDistricts: 'ಹೆಚ್ಚು ವರದಿಯಾದ ಪ್ರಕರಣಗಳ ಜಿಲ್ಲೆಗಳು', noTrendRecords: 'ಈ ಫಿಲ್ಟರ್‌ಗಳಿಗೆ ದಾಖಲೆಗಳಿಲ್ಲ.', latestReport: 'ಇತ್ತೀಚಿನ ವರದಿ', trendCoverage: 'ಗಮನಿಸಿ: ಶ್ರೇಯಾಂಕವು API ಹಿಂತಿರುಗಿಸಿದ ಗರಿಷ್ಠ 500 ಲಭ್ಯ ವರದಿಗಳನ್ನು ಮಾತ್ರ ಆಧರಿಸಿದೆ. ಇದು ನೇರ ಅಥವಾ ಅಧಿಕೃತ ರೋಗ ಹರಡುವಿಕೆ ಘೋಷಣೆ ಅಲ್ಲ.', recordsLine: 'ದಾಖಲೆಗಳು', casesLine: 'ಪ್ರಕರಣಗಳು', deathsLine: 'ಸಾವುಗಳು' },
  hi: { overview: 'अवलोकन', evidence: 'साक्ष्य', sources: 'स्रोत', appTitle: 'संरक्षा केंद्र', eyebrow: 'सार्वजनिक स्वास्थ्य जानकारी', summary: 'निगरानी एक नज़र में', totalRecords: 'रिकॉर्ड', cases: 'रिपोर्ट किए गए मामले', deaths: 'रिपोर्ट की गई मौतें', states: 'राज्य / केंद्र शासित प्रदेश', diseases: 'बीमारी लेबल', hospitals: 'अस्पताल निर्देशिका', refresh: 'डेटा रीफ़्रेश', available: 'उपलब्ध', unavailable: 'अनुपलब्ध', loading: 'डेटा लोड हो रहा है…', offline: 'API डेटा लोड नहीं हुआ। कनेक्शन जाँचकर पुनः प्रयास करें।', noSources: 'स्रोत स्थिति अभी उपलब्ध नहीं है।', askTitle: 'साक्ष्य सहायक से पूछें', prompt: 'लोड किए गए निगरानी डेटा के बारे में पूछें…', send: 'पूछें', asking: 'डेटा जाँचा जा रहा है…', prompts: ['निगरानी डेटासेट का सारांश', 'top diseases', 'weekly trend', 'total cases in Karnataka'], sourcesForAnswer: 'स्रोत', disclaimer: 'ध्यान दें: उत्तर केवल इस स्थापना में लोड रिकॉर्ड तक सीमित हैं। यह चिकित्सकीय सलाह या आधिकारिक प्रकोप घोषणा नहीं है।', sourceWarning: 'प्रकाशन सूचनाएँ निरंतर केस-काउंट फ़ीड नहीं हैं।', emptyAnswer: 'स्रोत-आधारित उत्तर के लिए प्रश्न पूछें।', error: 'समस्या हुई। कृपया फिर प्रयास करें।', trends: 'रुझान', trendTitle: 'ज़िला-स्तरीय प्रकोप रुझान', trendHint: 'उपलब्ध IDSP रिपोर्ट देखें। फ़िल्टर API से मिले रिकॉर्ड पर लागू होते हैं।', diseaseFilter: 'बीमारी फ़िल्टर', stateFilter: 'राज्य फ़िल्टर', dateFrom: 'शुरुआती तारीख (YYYY-MM-DD)', dateTo: 'अंतिम तारीख (YYYY-MM-DD)', refreshTrends: 'रिपोर्ट रीफ़्रेश करें', clearFilters: 'फ़िल्टर हटाएँ', recordsFound: 'मेल खाते रिकॉर्ड', topDistricts: 'सबसे अधिक रिपोर्ट किए गए मामलों वाले ज़िले', noTrendRecords: 'इन फ़िल्टर से कोई रिकॉर्ड नहीं मिला।', latestReport: 'नवीनतम रिपोर्ट', trendCoverage: 'ध्यान दें: रैंकिंग API से लौटाई गई अधिकतम 500 उपलब्ध रिपोर्टों पर आधारित है। यह लाइव या आधिकारिक प्रकोप घोषणा नहीं है।', recordsLine: 'रिकॉर्ड', casesLine: 'मामले', deathsLine: 'मौतें' },
};

const fmt = (value) => Number(value ?? 0).toLocaleString('en-IN');
const safeCount = (value) => { const number = Number(value ?? 0); return Number.isFinite(number) && number > 0 ? number : 0; };

function ActionButton({ children, onPress, disabled, secondary = false, accessibilityLabel }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel || String(children)} onPress={onPress} disabled={disabled} style={({ pressed }) => [styles.button, secondary && styles.buttonSecondary, disabled && styles.buttonDisabled, pressed && !disabled && styles.buttonPressed]}><Text style={[styles.buttonText, secondary && styles.buttonTextSecondary]}>{children}</Text></Pressable>;
}

function StatCard({ label, value, accent = false }) {
  const displayValue = displayStatValue(value, fmt);
  return <View style={[styles.statCard, accent && styles.statCardAccent]}><Text style={[styles.statLabel, accent && styles.statLabelAccent]}>{label}</Text><Text accessibilityRole="text" style={[styles.statValue, accent && styles.statValueAccent]}>{displayValue}</Text></View>;
}

function WeeklyCasesChart({ points = [] }) {
  const chartPoints = prepareWeeklyChartPoints(points, 8);
  const maximum = Math.max(1, ...chartPoints.map((point) => point.cases));
  return <View style={styles.chartCard}>
    <View style={styles.chartHead}><Text style={styles.chartTitle}>Reported cases by reporting week</Text><Text style={styles.chartCaption}>Latest {chartPoints.length || 0} periods</Text></View>
    {chartPoints.length ? <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.weeklyChartBars}>
      {chartPoints.map((point, index) => <View key={`${point.period}-${index}`} style={styles.weeklyChartColumn}>
        <Text numberOfLines={1} style={styles.weeklyChartValue}>{fmt(point.cases)}</Text>
        <View style={styles.weeklyChartArea}><View style={[styles.weeklyChartBar, { height: Math.max(3, (point.cases / maximum) * 86) }]} /></View>
        <Text numberOfLines={1} style={styles.weeklyChartLabel}>{compactPeriodLabel(point.period)}</Text>
      </View>)}
    </ScrollView> : <Text style={styles.chartEmpty}>No weekly trend points were returned by the API.</Text>}
    <Text style={styles.chartCaption}>Reported values from the available records; not a live case-count stream.</Text>
  </View>;
}

function RankingBars({ title, items = [] }) {
  const rows = prepareRankingBars(items, 6);
  return <View style={styles.chartCard}>
    <Text style={styles.chartTitle}>{title}</Text>
    {rows.length ? rows.map((item, index) => <View key={`${item.name}-${index}`} style={styles.rankRow}>
      <Text numberOfLines={1} ellipsizeMode="tail" style={styles.rankLabel}>{item.name}</Text>
      <View style={styles.rankTrack}><View style={[styles.rankFill, { width: `${item.percent}%` }]} /></View>
      <Text style={styles.rankValue}>{fmt(item.value)}</Text>
    </View>) : <Text style={styles.chartEmpty}>No comparison data was returned for this chart.</Text>}
    <Text style={styles.chartCaption}>Ranked within the available summary response.</Text>
  </View>;
}

function IcaSignalsChart({ signals = [] }) {
  const chart = prepareIcaSignalData(signals, 6);
  return <View style={styles.chartCard}>
    <Text style={styles.chartTitle}>ICA component signals by reporting period</Text>
    <Text style={styles.chartCaption}>Positive and negative component scores scaled to this result.</Text>
    {!chart.periods.length || !chart.components.length ? <Text style={styles.chartEmpty}>No component series available to plot.</Text> : chart.periods.map((period, index) => <View key={`${period.period}-${index}`} style={styles.icaPeriod}>
      <Text style={styles.icaPeriodTitle}>{period.period}</Text>
      {period.values.map(({ component, value }) => {
        const width = `${Math.max(0, Math.min(50, (Math.abs(value) / chart.maxAbs) * 50))}%`;
        return <View key={`${period.period}-${component}`} style={styles.icaSignalRow}>
          <Text style={styles.icaSignalName}>{component}</Text>
          <View style={styles.icaAxis}><View style={styles.icaAxisCenter} />{value >= 0 ? <View style={[styles.icaPositive, { left: '50%', width }]} /> : <View style={[styles.icaNegative, { right: '50%', width }]} />}</View>
          <Text style={styles.icaSignalValue}>{value.toFixed(2)}</Text>
        </View>;
      })}
    </View>)}
  </View>;
}

export default function App() {
  const [tab, setTab] = useState('overview');
  const [language, setLanguage] = useState('en');
  const [token, setToken] = useState('');
  const [sessionLoading, setSessionLoading] = useState(true);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [summary, setSummary] = useState(null);
  const [hospitalCount, setHospitalCount] = useState(0);
  const [sources, setSources] = useState([]);
  const [trendRecords, setTrendRecords] = useState([]);
  const [trendsBusy, setTrendsBusy] = useState(false);
  const [trendsError, setTrendsError] = useState('');
  const [diseaseFilter, setDiseaseFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [busy, setBusy] = useState(false);
  const [pageError, setPageError] = useState('');
  const [question, setQuestion] = useState('');
  const [answerBusy, setAnswerBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [answerError, setAnswerError] = useState('');
  const [historyFilters, setHistoryFilters] = useState({ state: '', district: '', disease: '', year: '' });
  const [appliedHistoryFilters, setAppliedHistoryFilters] = useState({ state: '', district: '', disease: '', year: '' });
  const [historyPage, setHistoryPage] = useState(1);
  const [historyResult, setHistoryResult] = useState({ items: [], total: 0, pages: 1 });
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [globalFeed, setGlobalFeed] = useState(null);
  const [globalBusy, setGlobalBusy] = useState(false);
  const [globalError, setGlobalError] = useState('');
  const [indiaReports, setIndiaReports] = useState(null);
  const [indiaBusy, setIndiaBusy] = useState(false);
  const [indiaError, setIndiaError] = useState('');
  const [anomalies, setAnomalies] = useState([]);
  const [anomalyCaution, setAnomalyCaution] = useState('');
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [icaComponents, setIcaComponents] = useState(2);
  const [icaResult, setIcaResult] = useState(null);
  const [icaError, setIcaError] = useState('');
  const [liveStatus, setLiveStatus] = useState('connecting');
  const [liveEvents, setLiveEvents] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [liveNotice, setLiveNotice] = useState('');
  const [mapRecords, setMapRecords] = useState([]);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapBusy, setMapBusy] = useState(false);
  const [mapError, setMapError] = useState('');
  const [mapSelectedState, setMapSelectedState] = useState('');

  // Reviewer token is intentionally memory-only; it is never written to SecureStore.
  const [reviewerTokenInput, setReviewerTokenInput] = useState('');
  const [reviewerToken, setReviewerToken] = useState('');
  const [reviewerName, setReviewerName] = useState('');
  const [reviewItems, setReviewItems] = useState([]);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewPendingTotal, setReviewPendingTotal] = useState(0);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [reviewNotice, setReviewNotice] = useState('');
  const [reviewNotes, setReviewNotes] = useState({});
  const [reviewStatusFilter, setReviewStatusFilter] = useState('pending_supervisor_review');
  const [reviewAudit, setReviewAudit] = useState([]);
  const [reviewAuditVisible, setReviewAuditVisible] = useState(false);

  const [stagingSummary, setStagingSummary] = useState(null);
  const [stagingLoaded, setStagingLoaded] = useState(false);
  const [stagingBusy, setStagingBusy] = useState(false);
  const [stagingError, setStagingError] = useState('');
  const [stagingRowsError, setStagingRowsError] = useState('');
  const [stagingItems, setStagingItems] = useState([]);
  const t = COPY[language] || COPY.en;

  // Restore only the access token from the OS-protected secure store. Never save the password.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const savedToken = await SecureStore.getItemAsync(SESSION_TOKEN_KEY);
        if (savedToken) {
          try {
            await requestJSON('/auth/me', { token: savedToken }, fetch, API_BASE);
            if (active) setToken(savedToken);
          } catch (error) {
            const message = String(error?.message || '');
            if (isSessionRejectedMessage(message)) {
              await SecureStore.deleteItemAsync(SESSION_TOKEN_KEY).catch(() => {});
              if (active) setLoginError('Your saved session has expired. Please sign in again.');
            } else if (active) {
              // Keep the token during temporary network failures; the dashboard can retry.
              setToken(savedToken);
            }
          }
        }
      } catch {
        // If secure storage cannot be read, show sign-in rather than failing to open the app.
      } finally {
        if (active) setSessionLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  const signIn = useCallback(async () => {
    const username = loginUsername.trim();
    if (!username || !loginPassword) {
      setLoginError('Enter your username and password.');
      return;
    }
    setLoginBusy(true);
    setLoginError('');
    try {
      const payload = await requestJSON('/auth/login', {
        method: 'POST',
        body: { username, password: loginPassword },
      }, fetch, API_BASE);
      const accessToken = extractAccessToken(payload);
      // Validate the token against the protected backend endpoint before persisting it.
      await requestJSON('/auth/me', { token: accessToken }, fetch, API_BASE);
      await SecureStore.setItemAsync(SESSION_TOKEN_KEY, accessToken);
      setToken(accessToken);
      setLoginPassword('');
      setLoginError('');
    } catch (error) {
      setLoginError(error?.message || 'Sign-in failed. Check your account details and try again.');
    } finally {
      setLoginBusy(false);
    }
  }, [loginUsername, loginPassword]);

  const signOut = useCallback(async () => {
    try {
      await SecureStore.deleteItemAsync(SESSION_TOKEN_KEY);
    } catch {
      setLoginError('Could not clear the secure session. Please try signing out again.');
      return;
    }
    setToken('');
    setSummary(null);
    setHospitalCount(0);
    setSources([]);
    setReviewerToken('');
    setReviewerTokenInput('');
    setReviewerName('');
    setReviewItems([]);
    setReviewAudit([]);
    setReviewAuditVisible(false);
    setStagingItems([]);
    setStagingSummary(null);
    setStagingLoaded(false);
    setAnswer(null);
    setAnswerError('');
    setPageError('');
    setTab('overview');
  }, []);

  const handleAuthFailure = useCallback(async (error) => {
    const message = String(error?.message || '');
    if (!isSessionRejectedMessage(message)) return false;
    try { await SecureStore.deleteItemAsync(SESSION_TOKEN_KEY); } catch { /* proceed to re-authenticate */ }
    setToken('');
    setLoginPassword('');
    setLoginError('Your session was rejected by the API. Please sign in again.');
    setPageError('');
    return true;
  }, []);

  const refreshData = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setPageError('');
    try {
      const [summaryData, hospitalData, sourceData] = await Promise.all([
        requestJSON('/public/surveillance/summary', { token }, fetch, API_BASE),
        requestJSON('/hospitals/count', { token }, fetch, API_BASE).catch(() => ({ count: 0 })),
        requestJSON('/system/source-status', { token }, fetch, API_BASE).catch(() => ({ sources: [] })),
      ]);
      const parsedSummary = parseSummary(summaryData);
      setSummary({
        ...parsedSummary,
        topStates: Array.isArray(summaryData.top_states) ? summaryData.top_states : [],
        topDiseases: Array.isArray(summaryData.top_diseases) ? summaryData.top_diseases : [],
      });
      setHospitalCount(Number(hospitalData.count ?? hospitalData.total ?? 0) || 0);
      setSources(parseSourceStatus(sourceData));
      setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setPageError(error?.message || t.offline);
    } finally {
      setBusy(false);
    }
  }, [token, t.offline, handleAuthFailure]);

  useEffect(() => { if (token) refreshData(); }, [token, refreshData]);

  const ask = useCallback(async (value = question) => {
    let body;
    try { body = buildAssistantRequest(value, language); }
    catch (error) { setAnswerError(error.message); return; }
    setQuestion(body.question);
    setAnswerError('');
    setAnswerBusy(true);
    try {
      const result = await requestJSON('/public/assistant/query', { method: 'POST', body, token }, fetch, API_BASE);
      setAnswer(result);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setAnswerError(error?.message || t.error);
    } finally {
      setAnswerBusy(false);
    }
  }, [question, language, token, t.error, handleAuthFailure]);

  const refreshTrends = useCallback(async () => {
    if (!token) return;
    setTrendsBusy(true);
    setTrendsError('');
    try {
      const data = await requestJSON('/idsp/records?limit=500', { token }, fetch, API_BASE);
      if (!Array.isArray(data)) throw new Error('The IDSP records endpoint returned an unexpected response.');
      setTrendRecords(data);
      setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setTrendsError(error?.message || 'Could not load district trends.');
    } finally {
      setTrendsBusy(false);
    }
  }, [token, handleAuthFailure]);

  useEffect(() => {
    if (token && tab === 'trends') refreshTrends();
  }, [token, tab, refreshTrends]);

  const refreshHistory = useCallback(async () => {
    if (!token) return;
    setHistoryBusy(true); setHistoryError('');
    try {
      const query = buildHistoryQuery(appliedHistoryFilters, historyPage, 30);
      const data = await requestJSON(`/public/surveillance?${query}`, { token }, fetch, API_BASE);
      setHistoryResult(normalizePagedRecords(data));
      setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setHistoryError(error?.message || 'Could not load historical reports.');
    } finally { setHistoryBusy(false); }
  }, [token, appliedHistoryFilters, historyPage, handleAuthFailure]);

  const refreshGlobalSignals = useCallback(async (forceRefresh = false) => {
    if (!token) return;
    setGlobalBusy(true); setGlobalError('');
    try {
      const data = await requestJSON(`/public/global-outbreaks?limit=25${forceRefresh ? '&force_refresh=true' : ''}`, { token }, fetch, API_BASE);
      setGlobalFeed(data); setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setGlobalError(error?.message || 'Could not load WHO global outbreak notices.');
    } finally { setGlobalBusy(false); }
  }, [token, handleAuthFailure]);

  const refreshIndiaReports = useCallback(async (forceRefresh = false) => {
    if (!token) return;
    setIndiaBusy(true); setIndiaError('');
    try {
      const data = await requestJSON(`/public/india-outbreak-reports?limit=50${forceRefresh ? '&force_refresh=true' : ''}`, { token }, fetch, API_BASE);
      setIndiaReports(data); setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setIndiaError(error?.message || 'Could not load NCDC/IDSP report catalogue.');
    } finally { setIndiaBusy(false); }
  }, [token, handleAuthFailure]);

  const refreshAnomalies = useCallback(async () => {
    if (!token) return;
    setAnalysisBusy(true); setAnomalyCaution('');
    try {
      const data = await requestJSON('/analytics/anomalies', { token }, fetch, API_BASE);
      setAnomalies(Array.isArray(data.items) ? data.items : []);
      setAnomalyCaution(data.caution || 'Screening results require human review.');
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setAnomalyCaution(error?.message || 'Could not load historical screening results.');
    } finally { setAnalysisBusy(false); }
  }, [token, handleAuthFailure]);

  const refreshMapData = useCallback(async () => {
    if (!token) return;
    setMapBusy(true); setMapError('');
    try {
      const records = await requestJSON('/idsp/records?limit=500', { token }, fetch, API_BASE);
      if (!Array.isArray(records)) throw new Error('IDSP records response is not an array.');
      setMapRecords(records);
      try {
        const candidateData = await requestJSON('/analytics/anomalies', { token }, fetch, API_BASE);
        setAnomalies(Array.isArray(candidateData.items) ? candidateData.items : []);
        setAnomalyCaution(candidateData.caution || 'Historical statistical candidates require human review.');
      } catch (candidateError) {
        if (await handleAuthFailure(candidateError)) return;
        setMapError('Map records loaded, but historical anomaly candidates could not be refreshed.');
      }
      setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setMapError(error?.message || 'Could not load map and hotspot data.');
    } finally { setMapBusy(false); setMapLoaded(true); }
  }, [token, handleAuthFailure]);

  const loadReviewerQueue = useCallback(async (candidateToken = reviewerTokenInput, status = reviewStatusFilter) => {
    const activeReviewerToken = String(candidateToken || '').trim();
    if (!activeReviewerToken) { setReviewError('Enter the NCDC_REVIEWER_TOKEN configured by the project administrator.'); return; }
    if (!token) { setReviewError('Sign in to the Samraksha Kendra application first.'); return; }
    setReviewLoading(true); setReviewError(''); setReviewNotice('');
    try {
      const params = new URLSearchParams({ status, limit: '50', offset: '0' });
      const payload = await requestJSON(`/review/ncdc/staging?${params.toString()}`, {
        token,
        headers: { 'X-Reviewer-Token': activeReviewerToken },
      }, fetch, API_BASE);
      const normalized = normalizeReviewerQueue(payload);
      setReviewerToken(activeReviewerToken);
      setReviewerTokenInput('');
      setReviewItems(normalized.items);
      setReviewTotal(normalized.total);
      setReviewPendingTotal(normalized.pendingTotal);
      setReviewStatusFilter(status);
      setStagingLoaded(false);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setReviewError(error?.message || 'Could not access the protected NCDC review queue.');
    } finally { setReviewLoading(false); }
  }, [token, reviewerTokenInput, reviewerName, reviewStatusFilter, handleAuthFailure]);

  const loadReviewAudit = useCallback(async () => {
    if (!reviewerToken || !token) return;
    setReviewLoading(true); setReviewError('');
    try {
      const payload = await requestJSON('/review/ncdc/audit?limit=100', {
        token,
        headers: { 'X-Reviewer-Token': reviewerToken },
      }, fetch, API_BASE);
      setReviewAudit(Array.isArray(payload.items) ? payload.items : []);
      setReviewAuditVisible(true);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setReviewError(error?.message || 'Could not load review audit history.');
    } finally { setReviewLoading(false); }
  }, [token, reviewerToken, handleAuthFailure]);

  const decideStagedRecord = useCallback(async (record, decision) => {
    if (!reviewerToken || !token) return;
    let payload;
    try { payload = buildReviewerDecision(record, decision, reviewerName, reviewNotes[record.record_id] || ''); }
    catch (error) { setReviewError(error?.message || 'Review decision is incomplete.'); return; }
    setReviewLoading(true); setReviewError(''); setReviewNotice('');
    try {
      const result = await requestJSON('/review/ncdc/decision', {
        method: 'POST', token, body: payload,
        headers: { 'X-Reviewer-Token': reviewerToken },
      }, fetch, API_BASE);
      setReviewNotice(`${result.record_id} marked ${result.review_status || decision}. The live IDSP surveillance table was not changed.`);
      setReviewNotes((previous) => ({ ...previous, [record.record_id]: '' }));
      await loadReviewerQueue(reviewerToken, reviewStatusFilter);
      setStagingLoaded(false);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setReviewError(error?.message || 'Could not save the review decision.');
    } finally { setReviewLoading(false); }
  }, [token, reviewerToken, reviewerName, reviewNotes, reviewStatusFilter, loadReviewerQueue, handleAuthFailure]);

  const refreshStaging = useCallback(async () => {
    if (!token) return;
    setStagingBusy(true); setStagingError(''); setStagingRowsError('');
    try {
      const summaryPayload = await requestJSON('/admin/ncdc-staging/summary', { token }, fetch, API_BASE);
      setStagingSummary(normalizeStagingSummary(summaryPayload));
      if (reviewerToken) {
        try {
          const params = new URLSearchParams({ status: 'all', limit: '30', offset: '0' });
          const detailPayload = await requestJSON(`/review/ncdc/staging?${params.toString()}`, {
            token, headers: { 'X-Reviewer-Token': reviewerToken },
          }, fetch, API_BASE);
          setStagingItems(normalizeReviewerQueue(detailPayload).items);
        } catch (detailError) {
          if (await handleAuthFailure(detailError)) return;
          setStagingRowsError(detailError?.message || 'Could not load staged row details.');
          setStagingItems([]);
        }
      } else {
        setStagingItems([]);
      }
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setStagingError(error?.message || 'Could not load staged NCDC summary.');
    } finally { setStagingBusy(false); setStagingLoaded(true); }
  }, [token, reviewerToken, handleAuthFailure]);

  useEffect(() => {
    if (token && tab === 'map' && !mapLoaded && !mapBusy) refreshMapData();
  }, [token, tab, mapLoaded, mapBusy, refreshMapData]);

  useEffect(() => {
    if (token && tab === 'staging' && !stagingLoaded && !stagingBusy) refreshStaging();
  }, [token, tab, stagingLoaded, stagingBusy, refreshStaging]);

  const runHistoricalScreening = useCallback(async () => {
    if (!token) return;
    setAnalysisBusy(true); setAnomalyCaution('');
    try {
      const data = await requestJSON('/analytics/anomalies/run', { method: 'POST', token }, fetch, API_BASE);
      setAnomalies(Array.isArray(data.items) ? data.items : []);
      setAnomalyCaution(`Screening finished: ${Number(data.count || 0)} potential flags. Automated screening only; human review is required.`);
      setLiveNotice(`Historical screening completed; ${Number(data.delivered_messages || 0)} live notification(s) delivered.`);
      setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setAnomalyCaution(error?.message || 'Historical screening failed.');
    } finally { setAnalysisBusy(false); }
  }, [token, handleAuthFailure]);

  const sendSyntheticDemo = useCallback(async () => {
    if (!token) return;
    setAnalysisBusy(true);
    try {
      const data = await requestJSON('/analytics/demo-anomaly', { method: 'POST', token }, fetch, API_BASE);
      setLiveNotice(`DEMO ONLY: synthetic notification broadcast to ${Number(data.delivered_clients || 0)} connected client(s). No data records were changed.`);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setAnomalyCaution(error?.message || 'Could not broadcast the demo notification.');
    } finally { setAnalysisBusy(false); }
  }, [token, handleAuthFailure]);

  const loadIca = useCallback(async () => {
    if (!token) return;
    setAnalysisBusy(true); setIcaError(''); setIcaResult(null);
    try {
      const data = await requestJSON(`/analytics/ica?components=${icaComponents}`, { token }, fetch, API_BASE);
      setIcaResult(data); setLastUpdated(new Date().toISOString());
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      setIcaError(error?.message || 'ICA analysis could not run with the current dataset.');
    } finally { setAnalysisBusy(false); }
  }, [token, icaComponents, handleAuthFailure]);

  const exportHistoryCsv = useCallback(async () => {
    if (!token) return;
    try {
      const query = buildHistoryQuery(appliedHistoryFilters);
      const response = await fetch(`${API_BASE}/public/surveillance/export.csv${query ? `?${query}` : ''}`, { headers: { Accept: 'text/csv', Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error(response.status === 401 ? 'Session was rejected. Please sign in again.' : `CSV export failed (HTTP ${response.status}).`);
      const csv = await response.text();
      const target = `${FileSystem.cacheDirectory}samraksha-surveillance-${Date.now()}.csv`;
      await FileSystem.writeAsStringAsync(target, csv, { encoding: FileSystem.EncodingType.UTF8 });
      if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(target, { mimeType: 'text/csv', dialogTitle: 'Export surveillance records' });
      else Alert.alert('CSV exported', `Saved to ${target}`);
    } catch (error) {
      if (await handleAuthFailure(error)) return;
      Alert.alert('Export failed', error?.message || 'Could not export the selected data.');
    }
  }, [token, appliedHistoryFilters, handleAuthFailure]);

  // The API snapshot is refreshed every minute while the app is foregrounded. WHO/NCDC
  // publication feeds have their own upstream cadence and are refreshed only while viewed.
  useEffect(() => {
    if (!token) return undefined;
    const refreshVisibleData = () => {
      if (AppState.currentState !== 'active') return;
      refreshData();
      if (tab === 'trends') refreshTrends();
      if (tab === 'history') refreshHistory();
      if (tab === 'signals') refreshGlobalSignals(false);
      if (tab === 'india') refreshIndiaReports(false);
    };
    const timer = setInterval(refreshVisibleData, SNAPSHOT_REFRESH_MS);
    const feedTimer = setInterval(() => {
      if (AppState.currentState !== 'active') return;
      if (tab === 'signals') refreshGlobalSignals(false);
      if (tab === 'india') refreshIndiaReports(false);
    }, OFFICIAL_FEED_REFRESH_MS);
    const subscription = AppState.addEventListener('change', (state) => { if (state === 'active') refreshVisibleData(); });
    return () => { clearInterval(timer); clearInterval(feedTimer); subscription?.remove?.(); };
  }, [token, tab, refreshData, refreshTrends, refreshHistory, refreshGlobalSignals, refreshIndiaReports]);

  // Push notifications arrive when a screening/demo event is broadcast by the backend.
  // Polling remains the fallback for snapshots because source data is not a continuous case feed.
  useEffect(() => {
    if (!token) { setLiveStatus('offline'); return undefined; }
    let stopped = false; let socket; let reconnectTimer; let heartbeatTimer;
    const connect = () => {
      if (stopped) return;
      try {
        const wsUrl = apiToWebSocketUrl(API_BASE);
        socket = new WebSocket(wsUrl);
        socket.onopen = () => {
          if (stopped) return;
          setLiveStatus('live');
          try { socket.send('ping'); } catch { /* heartbeat will retry */ }
          heartbeatTimer = setInterval(() => { try { if (socket?.readyState === 1) socket.send('ping'); } catch { /* reconnect handles failures */ } }, SOCKET_HEARTBEAT_MS);
        };
        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'connection_ready' || payload.type === 'pong') return;
            setLiveEvents((items) => [payload, ...items].slice(0, 20));
            setLiveNotice(payload.is_synthetic ? 'DEMO ONLY: synthetic event received; no surveillance rows were changed.' : `New screening event received: ${payload.disease || payload.type || 'surveillance event'}.`);
            refreshData();
            if (tab === 'trends') refreshTrends();
            if (tab === 'history') refreshHistory();
          } catch { /* ignore non-JSON frames */ }
        };
        socket.onerror = () => setLiveStatus('offline');
        socket.onclose = () => {
          if (heartbeatTimer) clearInterval(heartbeatTimer);
          setLiveStatus('reconnecting');
          if (!stopped) reconnectTimer = setTimeout(connect, SOCKET_RETRY_MS);
        };
      } catch { setLiveStatus('offline'); if (!stopped) reconnectTimer = setTimeout(connect, SOCKET_RETRY_MS); }
    };
    connect();
    return () => { stopped = true; clearTimeout(reconnectTimer); clearInterval(heartbeatTimer); try { socket?.close(); } catch { /* ignore close failures */ } };
  }, [token, tab, refreshData, refreshTrends, refreshHistory]);

  useEffect(() => { if (token && tab === 'history') refreshHistory(); }, [token, tab, refreshHistory]);
  useEffect(() => { if (token && tab === 'signals' && !globalFeed && !globalBusy) refreshGlobalSignals(false); }, [token, tab, globalFeed, globalBusy, refreshGlobalSignals]);
  useEffect(() => { if (token && tab === 'india' && !indiaReports && !indiaBusy) refreshIndiaReports(false); }, [token, tab, indiaReports, indiaBusy, refreshIndiaReports]);
  useEffect(() => { if (token && tab === 'anomalies' && anomalies.length === 0 && !analysisBusy && !anomalyCaution) refreshAnomalies(); }, [token, tab, anomalies.length, analysisBusy, anomalyCaution, refreshAnomalies]);

  const filteredTrendRecords = filterTrendRecords(trendRecords, {
    disease: diseaseFilter, state: stateFilter, fromDate, toDate,
  });
  const districtTotals = aggregateDistrictTrends(filteredTrendRecords).slice(0, 10);
  const selectedDistrictReports = selectedDistrict
    ? getDistrictReportDetails(filteredTrendRecords, selectedDistrict.district, selectedDistrict.state)
    : [];
  const trendCaseTotal = filteredTrendRecords.reduce((sum, record) => sum + safeCount(record.cases), 0);
  const trendDeathTotal = filteredTrendRecords.reduce((sum, record) => sum + safeCount(record.deaths), 0);
  const maxDistrictCases = Math.max(1, ...districtTotals.map((record) => record.cases));
  const clearTrendFilters = () => {
    setDiseaseFilter(''); setStateFilter(''); setFromDate(''); setToDate(''); setSelectedDistrict(null);
  };

  const pickPrompt = (prompt) => {
    setQuestion(prompt);
    ask(prompt);
  };

  if (sessionLoading) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar barStyle="light-content" backgroundColor={COLORS.navy} />
        <View style={styles.loading}>
          <ActivityIndicator size="large" color={COLORS.teal} />
          <Text style={styles.muted}>Restoring secure session…</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!token) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar barStyle="light-content" backgroundColor={COLORS.navy} />
        <ScrollView contentContainerStyle={styles.loginContent} keyboardShouldPersistTaps="handled">
          <View style={styles.loginCard}>
            <View style={styles.loginBrandRow}>
              <View style={styles.logo}><Text style={styles.logoText}>SK</Text></View>
              <Text style={styles.loginEyebrow}>PUBLIC HEALTH INTELLIGENCE</Text>
            </View>
            <Text style={styles.loginTitle}>Samraksha Kendra</Text>
            <Text style={styles.loginHint}>Sign in with your existing authorized Samraksha Kendra account to load surveillance data and use the Evidence Assistant.</Text>
            <Text style={styles.loginLabel}>Username</Text>
            <TextInput
              accessibilityLabel="Username"
              value={loginUsername}
              onChangeText={setLoginUsername}
              autoCapitalize="none"
              autoCorrect={false}
              textContentType="username"
              placeholder="Enter username"
              placeholderTextColor={COLORS.muted}
              style={styles.loginInput}
              returnKeyType="next"
            />
            <Text style={styles.loginLabel}>Password</Text>
            <TextInput
              accessibilityLabel="Password"
              value={loginPassword}
              onChangeText={setLoginPassword}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              textContentType="password"
              placeholder="Enter password"
              placeholderTextColor={COLORS.muted}
              style={styles.loginInput}
              onSubmitEditing={signIn}
              returnKeyType="go"
            />
            {!!loginError && <View style={styles.errorBox}><Text style={styles.errorText}>{loginError}</Text></View>}
            <ActionButton onPress={signIn} disabled={loginBusy}>
              {loginBusy ? 'Signing in…' : 'Sign in'}
            </ActionButton>
            <Text style={styles.loginFootnote}>Your password is sent only to the configured Samraksha Kendra API over HTTPS. It is not saved by this app.</Text>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

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
        <Pressable accessibilityRole="button" onPress={signOut} style={styles.signOutButton}><Text style={styles.signOutText}>Sign out</Text></Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabs} contentContainerStyle={styles.tabsContent}>
        {[
          ['overview', t.overview], ['history', 'Historical'], ['trends', t.trends],
          ['map', 'Map & hotspots'], ['alerts', 'Live alerts'],
          ['signals', 'Global signals'], ['india', 'India reports'], ['anomalies', 'Anomalies'],
          ['review', 'Report review queue'], ['staging', 'Staged NCDC data'],
          ['ica', 'ICA lab'], ['evidence', t.evidence], ['sources', t.sources],
        ].map(([id, label]) => <Pressable key={id} accessibilityRole="tab" accessibilityState={{ selected: tab === id }} onPress={() => setTab(id)} style={[styles.tab, tab === id && styles.tabActive]}><Text style={[styles.tabText, tab === id && styles.tabTextActive]}>{label}</Text></Pressable>)}
      </ScrollView>
      <View style={styles.liveStrip}>
        <View style={[styles.liveDot, liveStatus === 'live' ? styles.liveDotOn : styles.liveDotOff]} />
        <Text style={styles.liveStripText}>{liveStatus === 'live' ? 'Live alert stream connected' : liveStatus === 'reconnecting' ? 'Reconnecting live alert stream…' : liveStatus === 'connecting' ? 'Connecting live alert stream…' : 'Live alert stream offline'}</Text>
        <Text style={styles.liveStripText}>{lastUpdated ? `Updated ${new Date(lastUpdated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Not refreshed yet'}</Text>
      </View>
      {!!liveNotice && <Pressable onPress={() => setLiveNotice('')} style={styles.liveNotice}><Text style={styles.liveNoticeText}>{liveNotice}  ×</Text></Pressable>}

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
            <WeeklyCasesChart points={summary.weeklyTrend} />
            <RankingBars title="Top reported states" items={summary.topStates} />
            <RankingBars title="Most reported diseases" items={summary.topDiseases} />
            <View style={styles.noteCard}><Text style={styles.noteTitle}>DATA COVERAGE</Text><Text style={styles.noteText}>{t.disclaimer}</Text></View>
          </> : null}
        </>}

        {tab === 'trends' && <>
          <Text style={styles.sectionKicker}>IDSP SURVEILLANCE</Text>
          <Text style={styles.sectionTitle}>{t.trendTitle}</Text>
          <Text style={styles.bodyCopy}>{t.trendHint}</Text>
          <View style={styles.trendFilterRow}>
            <TextInput accessibilityLabel={t.diseaseFilter} value={diseaseFilter} onChangeText={setDiseaseFilter} placeholder={t.diseaseFilter} placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} autoCapitalize="none" />
            <TextInput accessibilityLabel={t.stateFilter} value={stateFilter} onChangeText={setStateFilter} placeholder={t.stateFilter} placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} autoCapitalize="words" />
          </View>
          <View style={styles.trendFilterRow}>
            <TextInput accessibilityLabel={t.dateFrom} value={fromDate} onChangeText={setFromDate} placeholder={t.dateFrom} placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} autoCapitalize="none" />
            <TextInput accessibilityLabel={t.dateTo} value={toDate} onChangeText={setToDate} placeholder={t.dateTo} placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} autoCapitalize="none" />
          </View>
          <View style={styles.trendActions}>
            <View style={styles.trendActionCell}><ActionButton onPress={refreshTrends} disabled={trendsBusy}>{trendsBusy ? '…' : t.refreshTrends}</ActionButton></View>
            <View style={styles.trendActionCell}><ActionButton secondary onPress={clearTrendFilters}>{t.clearFilters}</ActionButton></View>
          </View>
          {!!trendsError && <View style={styles.errorBox}><Text style={styles.errorText}>{trendsError}</Text><ActionButton onPress={refreshTrends}>{t.refreshTrends}</ActionButton></View>}
          {trendsBusy && trendRecords.length === 0 ? <View style={styles.loading}><ActivityIndicator size="large" color={COLORS.teal} /><Text style={styles.muted}>{t.loading}</Text></View> : <>
            <View style={styles.statsGrid}>
              <StatCard label={t.recordsFound} value={filteredTrendRecords.length} accent />
              <StatCard label={t.cases} value={trendCaseTotal} />
              <StatCard label={t.deaths} value={trendDeathTotal} />
            </View>
            <Text style={styles.trendSubheading}>{t.topDistricts}</Text>
            {districtTotals.length === 0 ? <View style={styles.noteCard}><Text style={styles.noteText}>{t.noTrendRecords}</Text></View> : districtTotals.map((district) => <Pressable accessibilityRole="button" accessibilityLabel={`Open reports for ${district.district}, ${district.state}`} onPress={() => setSelectedDistrict({ district: district.district, state: district.state })} key={`${district.state}-${district.district}`} style={[styles.districtCard, selectedDistrict?.district === district.district && selectedDistrict?.state === district.state && styles.districtCardSelected]}>
              <View style={styles.districtTitleRow}>
                <Text style={styles.districtName}>{district.district}</Text>
                <Text style={styles.districtCases}>{fmt(district.cases)} {t.casesLine}</Text>
              </View>
              <Text style={styles.muted}>{district.state} · {fmt(district.deaths)} {t.deathsLine} · {fmt(district.records)} {t.recordsLine}</Text>
              <View style={styles.trendBarTrack}><View style={[styles.trendBar, { width: `${Math.max(2, (district.cases / maxDistrictCases) * 100)}%` }]} /></View>
              <Text style={styles.trendLatest}>{t.latestReport}: {district.latest || '—'}</Text>
              <Text style={styles.sourceLinkText}>Tap to view report details ↓</Text>
              {!!district.source_url && <Text style={styles.muted}>Latest source available below the district details</Text>}
            </Pressable>)}
            {!!selectedDistrict && <View style={styles.detailCard}>
              <View style={styles.detailHeader}>
                <View style={styles.detailHeaderCopy}>
                  <Text style={styles.noteTitle}>DISTRICT REPORT DETAILS</Text>
                  <Text style={styles.detailTitle}>{selectedDistrict.district}, {selectedDistrict.state}</Text>
                </View>
                <ActionButton secondary onPress={() => setSelectedDistrict(null)}>Close</ActionButton>
              </View>
              <Text style={styles.muted}>Showing records that match the current filters and selected district.</Text>
              {selectedDistrictReports.length === 0 ? <Text style={styles.noteText}>No detail records are available for this district under the current filters.</Text> : selectedDistrictReports.slice(0, 30).map((record, index) => {
                const reportDate = record.reporting_end_date || record.reporting_start_date || 'Date not reported';
                const safeSourceUrl = /^https?:\/\//i.test(String(record.source_url || '')) ? String(record.source_url) : '';
                return <View key={`${record.record_id || record.source_url || record.disease || 'report'}-${reportDate}-${index}`} style={styles.detailReport}>
                  <Text style={styles.detailDisease}>{record.disease || 'Disease not reported'}</Text>
                  <Text style={styles.detailMetrics}>{fmt(record.cases)} reported cases · {fmt(record.deaths)} reported deaths</Text>
                  <Text style={styles.muted}>Reporting period: {record.reporting_start_date || '—'} to {record.reporting_end_date || '—'}</Text>
                  <Text style={styles.muted}>Year: {record.year ?? '—'} · Week: {record.week ?? '—'} · Status: {record.outbreak_status || 'Not reported'}</Text>
                  <Text style={styles.muted}>Source: {record.source || 'Not reported'}</Text>
                  {!!safeSourceUrl && <Pressable accessibilityRole="link" onPress={() => Linking.openURL(safeSourceUrl).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open source report ↗</Text></Pressable>}
                </View>;
              })}
              {selectedDistrictReports.length > 30 && <Text style={styles.muted}>Showing the latest 30 of {selectedDistrictReports.length} matching records.</Text>}
              <Text style={styles.noteText}>These are reported records from the current API response, not a live outbreak confirmation or medical advice.</Text>
            </View>}
            <View style={styles.noteCard}><Text style={styles.noteTitle}>DATA COVERAGE</Text><Text style={styles.noteText}>{t.trendCoverage}</Text></View>
          </>}
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

        {tab === 'history' && <>
          <Text style={styles.sectionKicker}>PUBLIC DATA EXPLORER</Text>
          <Text style={styles.sectionTitle}>Historical surveillance</Text>
          <Text style={styles.bodyCopy}>Search the aggregate IDSP records available in this installation. Results are read-only and limited to the selected page.</Text>
          <View style={styles.trendFilterRow}>
            <TextInput accessibilityLabel="State filter" value={historyFilters.state} onChangeText={(value) => setHistoryFilters((old) => ({ ...old, state: value }))} placeholder="State (e.g. Karnataka)" placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} />
            <TextInput accessibilityLabel="District filter" value={historyFilters.district} onChangeText={(value) => setHistoryFilters((old) => ({ ...old, district: value }))} placeholder="District" placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} />
          </View>
          <View style={styles.trendFilterRow}>
            <TextInput accessibilityLabel="Disease filter" value={historyFilters.disease} onChangeText={(value) => setHistoryFilters((old) => ({ ...old, disease: value }))} placeholder="Disease" placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} />
            <TextInput accessibilityLabel="Year filter" value={historyFilters.year} onChangeText={(value) => setHistoryFilters((old) => ({ ...old, year: value }))} placeholder="Year (e.g. 2026)" keyboardType="number-pad" placeholderTextColor={COLORS.muted} style={styles.trendFilterInput} />
          </View>
          <View style={styles.trendActions}>
            <View style={styles.trendActionCell}><ActionButton onPress={() => { setHistoryPage(1); setAppliedHistoryFilters({ ...historyFilters }); }} disabled={historyBusy}>Apply filters</ActionButton></View>
            <View style={styles.trendActionCell}><ActionButton secondary onPress={() => { const empty = { state: '', district: '', disease: '', year: '' }; setHistoryFilters(empty); setAppliedHistoryFilters(empty); setHistoryPage(1); }}>Clear filters</ActionButton></View>
          </View>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton secondary onPress={exportHistoryCsv}>Export CSV</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={refreshHistory} disabled={historyBusy}>{historyBusy ? 'Refreshing…' : 'Refresh reports'}</ActionButton></View></View>
          <View style={styles.statsGrid}><StatCard label="Matching reports" value={historyResult.total} accent /><StatCard label="Page" value={safePageLabel(historyPage, historyResult.pages)} /></View>
          {!!historyError && <View style={styles.errorBox}><Text style={styles.errorText}>{historyError}</Text><ActionButton onPress={refreshHistory}>Retry</ActionButton></View>}
          {historyBusy && historyResult.items.length === 0 ? <View style={styles.loading}><ActivityIndicator size="large" color={COLORS.teal}/><Text style={styles.muted}>Loading historical records…</Text></View> : historyResult.items.length ? historyResult.items.map((row, index) => <View key={row.record_id || `${row.year}-${row.week}-${row.state}-${row.disease}-${index}`} style={styles.parityCard}>
            <View style={styles.sourceTop}><Text style={styles.detailDisease}>{row.disease || 'Disease not specified'}</Text><Text style={styles.metricInline}>{fmt(row.cases)} cases</Text></View>
            <Text style={styles.muted}>{row.state || 'State not specified'} · {row.district || 'District not specified'}</Text>
            <Text style={styles.muted}>Year {row.year ?? '—'} · Week {row.week ?? '—'} · Deaths {fmt(row.deaths)}</Text>
            <Text style={styles.muted}>Reporting: {row.reporting_start_date || '—'} to {row.reporting_end_date || '—'} · Status: {row.outbreak_status || 'Reported'}</Text>
            {/^https?:\/\//i.test(String(row.source_url || '')) ? <Pressable accessibilityRole="link" onPress={() => Linking.openURL(row.source_url).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>{row.source || 'Open source report'} ↗</Text></Pressable> : <Text style={styles.muted}>Source: {row.source || 'Not specified'}</Text>}
          </View>) : <View style={styles.noteCard}><Text style={styles.noteText}>No records matched these filters. Try clearing filters.</Text></View>}
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton secondary disabled={historyBusy || historyPage <= 1} onPress={() => setHistoryPage((p) => Math.max(1, p - 1))}>← Previous</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary disabled={historyBusy || historyPage >= historyResult.pages} onPress={() => setHistoryPage((p) => Math.min(historyResult.pages, p + 1))}>Next →</ActionButton></View></View>
          <Text style={styles.noteText}>Showing at most 30 rows per page. Export uses the selected filters. Historical reported data is not a continuous real-time case stream.</Text>
        </>}

        {tab === 'signals' && <>
          <Text style={styles.sectionKicker}>WHO PUBLICATION FEED</Text>
          <Text style={styles.sectionTitle}>Global outbreak signals</Text>
          <Text style={styles.bodyCopy}>Official WHO Disease Outbreak News notices. These are publication updates, not a continuously updated count of cases.</Text>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton onPress={() => refreshGlobalSignals(true)} disabled={globalBusy}>{globalBusy ? 'Checking…' : 'Refresh official feed'}</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={() => refreshGlobalSignals(false)} disabled={globalBusy}>Reload cache</ActionButton></View></View>
          {globalFeed && <View style={styles.noteCard}><Text style={styles.noteTitle}>SOURCE STATUS · {String(globalFeed.status || 'unknown').toUpperCase()}</Text><Text style={styles.noteText}>Items: {fmt(globalFeed.count)} · Last checked: {globalFeed.last_checked_at || '—'} · Last successful fetch: {globalFeed.last_successful_fetch_at || '—'}</Text>{!!globalFeed.warning && <Text style={styles.noteText}>{globalFeed.warning}</Text>}{!!globalFeed.source_error && <Text style={styles.errorText}>{globalFeed.source_error}</Text>}</View>}
          {!!globalError && <View style={styles.errorBox}><Text style={styles.errorText}>{globalError}</Text></View>}
          {globalBusy && !globalFeed ? <ActivityIndicator size="large" color={COLORS.teal}/> : (globalFeed?.items || []).map((item, index) => <View key={String(item.id || item.url || index)} style={styles.parityCard}><Text style={styles.detailDisease}>{item.title || 'WHO outbreak notice'}</Text><Text style={styles.muted}>Published: {item.publication_date ? new Date(item.publication_date).toLocaleDateString() : 'Date not provided'} · {item.source || 'WHO Disease Outbreak News'}</Text><Text style={styles.noteText}>{item.summary || 'Open the official notice for details.'}</Text>{/^https:\/\//i.test(String(item.url || '')) && <Pressable accessibilityRole="link" onPress={() => Linking.openURL(item.url).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open official WHO notice ↗</Text></Pressable>}</View>)}
          <Text style={styles.noteText}>The backend caches this feed; force refresh may be rate-limited to protect the upstream publication service.</Text>
        </>}

        {tab === 'india' && <>
          <Text style={styles.sectionKicker}>NCDC / IDSP</Text>
          <Text style={styles.sectionTitle}>India weekly outbreak reports</Text>
          <Text style={styles.bodyCopy}>Browse official national weekly report catalogue. Numeric counts are not automatically extracted from linked PDFs; published notices may be weekly rather than real time.</Text>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton onPress={() => refreshIndiaReports(true)} disabled={indiaBusy}>{indiaBusy ? 'Checking…' : 'Refresh official archive'}</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={() => refreshIndiaReports(false)} disabled={indiaBusy}>Reload cache</ActionButton></View></View>
          {indiaReports && <View style={styles.noteCard}><Text style={styles.noteTitle}>ARCHIVE STATUS · {String(indiaReports.status || 'unknown').toUpperCase()}</Text><Text style={styles.noteText}>Entries: {fmt(indiaReports.count)} · Last checked: {indiaReports.last_checked_at || '—'} · Last successful fetch: {indiaReports.last_successful_fetch_at || '—'}</Text>{!!indiaReports.warning && <Text style={styles.noteText}>{indiaReports.warning}</Text>}{!!indiaReports.source_error && <Text style={styles.errorText}>{indiaReports.source_error}</Text>}</View>}
          {!!indiaError && <View style={styles.errorBox}><Text style={styles.errorText}>{indiaError}</Text></View>}
          {indiaBusy && !indiaReports ? <ActivityIndicator size="large" color={COLORS.teal}/> : (indiaReports?.items || []).map((item, index) => <View key={String(item.url || `${item.year}-${item.week}-${index}`)} style={styles.parityCard}><Text style={styles.detailDisease}>{item.title || 'NCDC weekly outbreak report'}</Text><Text style={styles.muted}>{item.report_type === 'pdf' ? 'OFFICIAL REPORT PDF' : 'ARCHIVE ENTRY'} · {item.year ? `Year ${item.year}` : 'Year not shown'}{item.week ? ` · Week ${item.week}` : ''}</Text>{/^https:\/\//i.test(String(item.url || '')) && <Pressable accessibilityRole="link" onPress={() => Linking.openURL(item.url).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>{item.report_type === 'pdf' ? 'Open NCDC PDF ↗' : 'Open official archive ↗'}</Text></Pressable>}</View>)}
          <Text style={styles.noteText}>Official archive updates are periodic. This screen does not convert PDF tables to case counts or modify approved surveillance rows.</Text>
        </>}

        {tab === 'anomalies' && <>
          <Text style={styles.sectionKicker}>EXPLAINABLE SCREENING</Text>
          <Text style={styles.sectionTitle}>Anomaly detection</Text>
          <Text style={styles.bodyCopy}>Run the backend's historical screening rule (trailing median + robust MAD) against currently loaded observations. A flag is for human review, not an outbreak declaration.</Text>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton onPress={runHistoricalScreening} disabled={analysisBusy}>{analysisBusy ? 'Screening…' : 'Run historical screening'}</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={sendSyntheticDemo} disabled={analysisBusy}>Send demo event</ActionButton></View></View>
          <Text style={styles.noteText}>The demo button sends only a clearly labelled synthetic notification. It does not modify the surveillance database.</Text>
          <View style={styles.statsGrid}><StatCard label="Flagged patterns" value={anomalies.length} accent/><StatCard label="Live alerts received" value={liveEvents.length}/></View>
          {!!anomalyCaution && <View style={styles.noteCard}><Text style={styles.noteText}>{anomalyCaution}</Text></View>}
          {analysisBusy && anomalies.length === 0 ? <ActivityIndicator size="large" color={COLORS.teal}/> : anomalies.length ? anomalies.slice(0, 30).map((item, index) => <View key={`${item.state}-${item.disease}-${item.year}-${item.week}-${index}`} style={styles.parityCard}><View style={styles.sourceTop}><Text style={styles.detailDisease}>{item.disease || 'Disease signal'}</Text><Text style={styles.metricInline}>{item.severity || 'REVIEW'}</Text></View><Text style={styles.muted}>{item.state || 'State not specified'} · {item.year || '—'} / week {item.week || '—'}</Text><Text style={styles.bodyCopy}>{item.message || 'Unusual reported case count detected by the screening rule.'}</Text><Text style={styles.muted}>Observed: {fmt(item.cases)} · Baseline median: {fmt(item.baseline_median)} · Method: {item.method || 'Robust historical screen'}</Text></View>) : <View style={styles.noteCard}><Text style={styles.noteText}>No eligible historical patterns are flagged in the current dataset. This does not prove an outbreak is absent; the series may lack enough history.</Text></View>}
          <Text style={styles.trendSubheading}>Live notification stream · {liveStatus}</Text>
          {liveEvents.length ? liveEvents.slice(0, 10).map((event, index) => <View key={String(event.event_id || `${event.created_at}-${index}`)} style={styles.parityCard}><Text style={styles.detailDisease}>{event.is_synthetic ? 'DEMO ONLY · ' : ''}{event.disease || event.type || 'Surveillance notification'}</Text><Text style={styles.muted}>{event.created_at || 'Just received'} · {event.state || 'Area not specified'}</Text><Text style={styles.bodyCopy}>{event.message || `${fmt(event.cases)} reported cases`}</Text></View>) : <Text style={styles.muted}>No new events received. Run screening to broadcast genuine-data screening events when any flags exist.</Text>}
        </>}

        {tab === 'ica' && <>
          <Text style={styles.sectionKicker}>EXPERIMENTAL ANALYTICS</Text>
          <Text style={styles.sectionTitle}>Independent Component Analysis</Text>
          <Text style={styles.bodyCopy}>FastICA is an exploratory transform of weekly disease signals. It is not a validated outbreak prediction system and does not establish causation.</Text>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><Text style={styles.filterLabel}>Components</Text><View style={styles.componentChoices}>{[2,3,4,5].map((value) => <Pressable key={value} onPress={() => setIcaComponents(value)} style={[styles.componentChip, icaComponents === value && styles.componentChipActive]}><Text style={[styles.componentChipText, icaComponents === value && styles.componentChipTextActive]}>{value}</Text></Pressable>)}</View></View><View style={styles.trendActionCell}><ActionButton onPress={loadIca} disabled={analysisBusy}>{analysisBusy ? 'Analysing…' : 'Run FastICA'}</ActionButton></View></View>
          {!!icaError && <View style={styles.errorBox}><Text style={styles.errorText}>{icaError}</Text></View>}
          {icaResult ? <><View style={styles.statsGrid}><StatCard label="Reporting periods" value={icaResult.sample_count} accent/><StatCard label="Input signals" value={(icaResult.features || []).length}/><StatCard label="Components" value={icaResult.n_components}/></View><View style={styles.noteCard}><Text style={styles.noteTitle}>SELECTED DISEASE FEATURES</Text><Text style={styles.noteText}>{(icaResult.features || []).join(', ') || 'No varying disease features returned.'}</Text><Text style={styles.noteTitle}>RECENT COMPONENT SIGNALS</Text>{(icaResult.signals || []).slice(-6).map((row, index) => <Text key={`${row.period || index}`} style={styles.muted}>{row.period || 'Period'} · {Object.entries(row).filter(([key]) => key.startsWith('IC')).map(([key, value]) => `${key}: ${Number(value).toFixed(3)}`).join(' · ')}</Text>)}</View><IcaSignalsChart signals={icaResult.signals || []} /><View style={styles.noteCard}><Text style={styles.noteTitle}>INTERPRETATION</Text><Text style={styles.noteText}>{icaResult.interpretation_note || 'Interpret components as exploratory patterns only.'}</Text></View></> : <View style={styles.noteCard}><Text style={styles.noteText}>Run FastICA to view weekly component signals. The API may reject the experiment when the dataset has too few distinct periods.</Text></View>}
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

        {tab === 'map' && (() => {
          const snapshot = summarizeLatestStateReports(mapRecords);
          const anomalyKeys = anomalies.map((item) => normalizeStateKey(item.state));
          const selectedKey = normalizeStateKey(mapSelectedState);
          const selected = snapshot.states.find((item) => item.key === selectedKey);
          const latestRows = selected?.rows || [];
          const sortedStates = snapshot.states.slice(0, 8);
          return <>
            <Text style={styles.sectionKicker}>GEOGRAPHIC SURVEILLANCE</Text>
            <Text style={styles.sectionTitle}>India map & potential hotspots</Text>
            <Text style={styles.bodyCopy}>State-level view of the latest reporting week in the loaded IDSP records. Red states indicate historical statistical anomaly candidates and are not confirmed outbreaks.</Text>
            <ActionButton onPress={refreshMapData} disabled={mapBusy}>{mapBusy ? 'Refreshing map…' : 'Refresh map data'}</ActionButton>
            {!!mapError && <View style={styles.errorBox}><Text style={styles.errorText}>{mapError}</Text></View>}
            <View style={styles.statsGrid}>
              <StatCard label="Latest period" value={snapshot.period?.label || '—'} accent />
              <StatCard label="Source rows" value={snapshot.totalRecords} />
              <StatCard label="States / UT labels" value={snapshot.statesCount} />
              <StatCard label="Reported cases" value={snapshot.totalCases === null ? 'Unknown' : snapshot.totalCases} />
            </View>
            {mapBusy && mapRecords.length === 0 ? <View style={styles.loading}><ActivityIndicator size="large" color={COLORS.teal}/><Text style={styles.muted}>Loading map data…</Text></View> : <View style={styles.mapCard}>
              <Svg width="100%" height={430} viewBox="0 0 440 500" accessibilityLabel="Interactive India state and union territory map">
                {INDIA_STATE_PATHS.map((feature) => {
                  const status = colorForMapState(feature.name, snapshot, anomalyKeys);
                  const isSelected = selectedKey && normalizeStateKey(feature.name) === selectedKey;
                  return <Path key={feature.name} d={feature.path} fill={status.fill} stroke={isSelected ? COLORS.navy : '#FFFFFF'} strokeWidth={isSelected ? 2.1 : 0.8} onPress={() => setMapSelectedState(feature.name)} accessibilityRole="button" accessibilityLabel={`${feature.name}: ${status.cases === null ? 'unknown cases' : fmt(status.cases) + ' cases'}`} />;
                })}
              </Svg>
              <View style={styles.mapLegendRow}><View style={styles.mapLegendItem}><View style={[styles.mapLegendSwatch, { backgroundColor: '#9ADBD2' }]} /><Text style={styles.mapLegendText}>Reported activity</Text></View><View style={styles.mapLegendItem}><View style={[styles.mapLegendSwatch, { backgroundColor: '#C63C32' }]} /><Text style={styles.mapLegendText}>Historical candidate</Text></View><View style={styles.mapLegendItem}><View style={[styles.mapLegendSwatch, { backgroundColor: '#E3EAF2' }]} /><Text style={styles.mapLegendText}>No data</Text></View></View>
              <Text style={styles.chartCaption}>Map boundary attribution: AbhinavSwami28/india-official-geojson, MIT license as used by the desktop view. State-centroid/map areas are approximate; verify official boundaries before formal publication.</Text>
            </View>}
            <Text style={styles.trendSubheading}>States with most reported cases</Text>
            {sortedStates.length ? sortedStates.map((state) => {
              const flag = anomalyKeys.includes(state.key);
              return <Pressable key={state.key} accessibilityRole="button" onPress={() => setMapSelectedState(state.state)} style={[styles.districtCard, selectedKey === state.key && styles.districtCardSelected]}>
                <View style={styles.districtTitleRow}><Text style={styles.districtName}>{state.state}</Text><Text style={styles.districtCases}>{state.cases === null ? 'Unknown' : `${fmt(state.cases)} cases`}</Text></View>
                <Text style={styles.muted}>{fmt(state.records)} rows · {state.deaths === null ? 'Deaths unknown' : `${fmt(state.deaths)} deaths`}{flag ? ' · Historical candidate' : ''}</Text>
              </Pressable>;
            }) : <View style={styles.noteCard}><Text style={styles.noteText}>No valid year/week state records were returned. Missing counts remain unknown rather than being converted to zero.</Text></View>}
            {!!selected && <View style={styles.detailCard}>
              <Text style={styles.noteTitle}>SELECTED STATE / UT</Text><Text style={styles.detailTitle}>{selected.state}</Text>
              <Text style={styles.detailMetrics}>{selected.cases === null ? 'Cases unknown' : `${fmt(selected.cases)} reported cases`} · {selected.deaths === null ? 'Deaths unknown' : `${fmt(selected.deaths)} reported deaths`}</Text>
              <Text style={styles.muted}>{selected.records} row(s) in {snapshot.period?.label || 'the latest available period'}{selected.latestEndDate ? ` · latest end date ${selected.latestEndDate}` : ''}</Text>
              {latestRows.slice(0, 8).map((row, index) => <View key={`${row.record_id || row.disease || 'row'}-${index}`} style={styles.detailReport}>
                <Text style={styles.detailDisease}>{row.disease || 'Disease not specified'}</Text>
                <Text style={styles.muted}>{row.district || 'District not specified'} · {row.cases === null || row.cases === undefined ? 'Cases unknown' : `${fmt(row.cases)} cases`} · {row.deaths === null || row.deaths === undefined ? 'Deaths unknown' : `${fmt(row.deaths)} deaths`}</Text>
                {!!row.source_url && /^https:\/\//i.test(String(row.source_url)) && <Pressable onPress={() => Linking.openURL(String(row.source_url)).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open source ↗</Text></Pressable>}
              </View>)}
              <ActionButton secondary onPress={() => setMapSelectedState('')}>Clear selected state</ActionButton>
            </View>}
            <View style={styles.noteCard}><Text style={styles.noteTitle}>INTERPRETATION</Text><Text style={styles.noteText}>This shows the latest available year/week within records loaded by this installation. Red marks a historical statistical candidate, which may come from an earlier period. It is not a confirmed outbreak map or a patient-level location map.</Text></View>
          </>;
        })()}

        {tab === 'alerts' && <>
          <Text style={styles.sectionKicker}>REAL-TIME NOTIFICATIONS</Text>
          <Text style={styles.sectionTitle}>Live alert activity</Text>
          <View style={styles.statsGrid}><StatCard label="Stream status" value={liveStatus === 'live' ? 'Connected' : liveStatus} accent/><StatCard label="Events this session" value={liveEvents.length}/></View>
          <Text style={styles.bodyCopy}>Events are delivered over the authenticated WebSocket while the mobile app is connected. This is a session view, not a persistent alert history.</Text>
          <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton onPress={runHistoricalScreening} disabled={analysisBusy}>{analysisBusy ? 'Screening…' : 'Run historical screening'}</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={sendSyntheticDemo} disabled={analysisBusy}>Send demo event</ActionButton></View></View>
          <View style={styles.noteCard}><Text style={styles.noteText}>Demo notifications are explicitly marked synthetic and do not change surveillance rows. Historical anomaly screening requires adequate time-series history and human review.</Text></View>
          {liveEvents.length ? liveEvents.slice(0, 30).map((event, index) => <View key={String(event.event_id || `${event.created_at}-${index}`)} style={styles.parityCard}>
            <View style={styles.sourceTop}><Text style={styles.detailDisease}>{event.is_synthetic ? 'DEMO ONLY · ' : ''}{event.disease || event.type || 'Surveillance notification'}</Text><Text style={styles.metricInline}>{event.type || (event.is_synthetic ? 'synthetic' : 'alert')}</Text></View>
            <Text style={styles.muted}>{event.created_at || 'Just received'} · {event.state || 'Area not specified'}</Text><Text style={styles.bodyCopy}>{event.message || `${fmt(event.cases)} reported cases`}</Text>
          </View>) : <View style={styles.noteCard}><Text style={styles.noteText}>{liveStatus === 'live' ? 'No new events have arrived in this session yet. Run the historical screening action if you want to check for eligible genuine-data candidates.' : 'The event stream is not connected. Keep the app open and check the live status strip after reconnecting.'}</Text></View>}
        </>}

        {tab === 'review' && <>
          <Text style={styles.sectionKicker}>RESTRICTED REVIEW WORKFLOW</Text>
          <Text style={styles.sectionTitle}>Report review queue</Text>
          <Text style={styles.bodyCopy}>Review staged NCDC rows against the official source PDF. Decisions are audited and never automatically update the main IDSP surveillance totals.</Text>
          <View style={styles.noteCard}><Text style={styles.noteTitle}>REVIEWER ACCESS</Text><Text style={styles.noteText}>Use the separate NCDC_REVIEWER_TOKEN configured by the project administrator, not your application or database password. It is held in memory only and cleared when you sign out. Never send it in chat.</Text></View>
          <TextInput value={reviewerTokenInput} onChangeText={setReviewerTokenInput} placeholder="NCDC reviewer token" placeholderTextColor={COLORS.muted} secureTextEntry autoCapitalize="none" style={styles.input} accessibilityLabel="NCDC reviewer token" />
          <TextInput value={reviewerName} onChangeText={setReviewerName} placeholder="Reviewer name for audit" placeholderTextColor={COLORS.muted} style={styles.input} maxLength={120} accessibilityLabel="Reviewer name" />
          <ActionButton onPress={() => loadReviewerQueue(reviewerTokenInput || reviewerToken, reviewStatusFilter)} disabled={reviewLoading}>{reviewLoading ? 'Connecting…' : reviewerToken ? 'Refresh review queue' : 'Connect to review queue'}</ActionButton>
          {reviewerToken ? <>
            <View style={styles.statsGrid}><StatCard label="Current view" value={reviewTotal} accent/><StatCard label="Pending review" value={reviewPendingTotal}/></View>
            <Text style={styles.filterLabel}>Status filter</Text>
            <View style={styles.componentChoices}>{[['pending_supervisor_review','Pending'],['needs_correction','Correction'],['approved','Approved'],['rejected','Rejected'],['all','All']].map(([status,label]) => <Pressable key={status} onPress={() => loadReviewerQueue(reviewerToken,status)} style={[styles.componentChip, reviewStatusFilter === status && styles.componentChipActive]}><Text style={[styles.componentChipText, reviewStatusFilter === status && styles.componentChipTextActive]}>{label}</Text></Pressable>)}</View>
            <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton secondary onPress={loadReviewAudit} disabled={reviewLoading}>{reviewAuditVisible ? 'Refresh audit' : 'Load review audit'}</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={() => { setReviewerToken(''); setReviewerTokenInput(''); setReviewerName(''); setReviewItems([]); setReviewAudit([]); setReviewAuditVisible(false); setReviewNotice('Reviewer disconnected.'); }} disabled={reviewLoading}>Disconnect</ActionButton></View></View>
          </> : null}
          {!!reviewError && <View style={styles.errorBox}><Text style={styles.errorText}>{reviewError}</Text></View>}
          {!!reviewNotice && <View style={styles.noteCard}><Text style={styles.noteText}>{reviewNotice}</Text></View>}
          {reviewLoading && !reviewItems.length ? <ActivityIndicator size="large" color={COLORS.teal}/> : reviewItems.length ? reviewItems.map((record) => {
            const status = String(record.review_status || 'pending_supervisor_review');
            const canDecide = ['pending_supervisor_review','needs_correction'].includes(status);
            return <View key={record.record_id} style={styles.parityCard}>
              <View style={styles.sourceTop}><Text style={styles.detailDisease}>{record.disease || 'Disease not specified'}</Text><Text style={styles.metricInline}>{status.replace(/_/g,' ').toUpperCase()}</Text></View>
              <Text style={styles.muted}>{record.record_id} · {record.report_year || '—'} / Week {record.report_week || '—'}</Text>
              <View style={styles.reviewFactsGrid}><Text style={styles.reviewFact}>State: {record.state || 'Not specified'}</Text><Text style={styles.reviewFact}>District: {record.district || 'Not specified'}</Text><Text style={styles.reviewFact}>Cases: {record.cases === null || record.cases === undefined ? 'Unknown' : fmt(record.cases)}</Text><Text style={styles.reviewFact}>Deaths: {record.deaths === null || record.deaths === undefined ? 'Unknown' : fmt(record.deaths)}</Text></View>
              <Text style={styles.muted}>Start: {record.outbreak_start_date || 'Not supplied'} · Reporting: {record.reporting_date || 'Not supplied'}</Text>
              <Text style={styles.noteText}>{record.source_validation_note || 'No source validation note supplied.'}</Text>
              {!!record.review_notes && <Text style={styles.muted}>Previous note: {record.review_notes}</Text>}
              {!!record.source_url && /^https:\/\/(?:www\.)?ncdc\.mohfw\.gov\.in\//i.test(String(record.source_url)) && <Pressable onPress={() => Linking.openURL(String(record.source_url)).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open official NCDC source ↗</Text></Pressable>}
              {canDecide ? <>
                <TextInput value={reviewNotes[record.record_id] || ''} onChangeText={(value) => setReviewNotes((old) => ({ ...old, [record.record_id]: value }))} placeholder="Evidence / review note (required for correction or rejection)" placeholderTextColor={COLORS.muted} multiline style={[styles.input, styles.reviewNoteInput]} maxLength={2000}/>
                <View style={styles.trendActions}><View style={styles.trendActionCell}><ActionButton onPress={() => decideStagedRecord(record,'approved')} disabled={reviewLoading}>Approve</ActionButton></View><View style={styles.trendActionCell}><ActionButton secondary onPress={() => decideStagedRecord(record,'needs_correction')} disabled={reviewLoading}>Request correction</ActionButton></View></View>
                <ActionButton secondary onPress={() => decideStagedRecord(record,'rejected')} disabled={reviewLoading}>Reject record</ActionButton>
              </> : <Text style={styles.muted}>Reviewed by {record.reviewed_by || 'Unknown'} · {record.reviewed_at || 'Time unavailable'}</Text>}
            </View>;
          }) : reviewerToken && !reviewLoading ? <View style={styles.noteCard}><Text style={styles.noteText}>No rows match this status filter. Try All or Pending.</Text></View> : null}
          {reviewAuditVisible && <View style={styles.detailCard}><Text style={styles.noteTitle}>AUDIT HISTORY</Text>{reviewAudit.length ? reviewAudit.slice(0,50).map((item,index) => <View key={`${item.id || item.record_id}-${index}`} style={styles.detailReport}><Text style={styles.detailDisease}>{item.record_id || 'Record'} · {item.new_status || 'Decision'}</Text><Text style={styles.muted}>{item.reviewed_at || item.changed_at || 'Date unavailable'} · {item.reviewer || 'Reviewer unknown'}</Text><Text style={styles.noteText}>{item.notes || 'No note supplied.'}</Text>{/^https:\/\/(?:www\.)?ncdc\.mohfw\.gov\.in\//i.test(String(item.source_url || '')) && <Pressable onPress={() => Linking.openURL(String(item.source_url)).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Source PDF ↗</Text></Pressable>}</View>) : <Text style={styles.noteText}>No review audit rows returned.</Text>}</View>}
        </>}

        {tab === 'staging' && <>
          <Text style={styles.sectionKicker}>DATA QUALITY & GOVERNANCE</Text>
          <Text style={styles.sectionTitle}>Staged NCDC data</Text>
          <Text style={styles.bodyCopy}>Candidate rows extracted from weekly reports stay separate from live surveillance totals until a reviewer verifies each field. Unknown counts are not zero, and approval does not auto-import the row.</Text>
          <ActionButton onPress={refreshStaging} disabled={stagingBusy}>{stagingBusy ? 'Refreshing staging…' : 'Refresh staged-data summary'}</ActionButton>
          {!!stagingError && <View style={styles.errorBox}><Text style={styles.errorText}>{stagingError}</Text></View>}
          {stagingBusy && !stagingSummary ? <ActivityIndicator size="large" color={COLORS.teal}/> : stagingSummary ? <>
            <View style={styles.statsGrid}><StatCard label="Staged rows" value={stagingSummary.totalRecords} accent/><StatCard label="Pending review" value={stagingSummary.pending}/></View>
            <View style={styles.detailCard}><Text style={styles.noteTitle}>REVIEW STATUS COUNTS</Text>{Object.entries(stagingSummary.statusCounts).map(([name,count]) => <View key={name} style={styles.reviewStatusRow}><Text style={styles.reviewFact}>{name.replace(/_/g,' ')}</Text><Text style={styles.metricInline}>{fmt(count)}</Text></View>)}</View>
            <View style={styles.noteCard}><Text style={styles.noteText}>{stagingSummary.note} Staged data is not part of the 246 structured IDSP rows unless it goes through the explicit validated import process.</Text></View>
          </> : null}
          {reviewerToken ? <>
            <Text style={styles.trendSubheading}>Staged record preview · first 30 rows</Text>
            {!!stagingRowsError && <View style={styles.errorBox}><Text style={styles.errorText}>{stagingRowsError}</Text></View>}
            {stagingItems.length ? stagingItems.map((record,index) => <View key={`${record.record_id || 'staging'}-${index}`} style={styles.parityCard}>
              <View style={styles.sourceTop}><Text style={styles.detailDisease}>{record.disease || 'Disease not specified'}</Text><Text style={styles.metricInline}>{record.review_status || 'pending'}</Text></View>
              <Text style={styles.muted}>{record.record_id || 'ID not supplied'} · {record.report_year || '—'} / Week {record.report_week || '—'}</Text>
              <Text style={styles.reviewFact}>{record.state || 'State unknown'} · {record.district || 'District unknown'}</Text>
              <Text style={styles.muted}>Cases: {record.cases === null || record.cases === undefined ? 'Unknown' : fmt(record.cases)} · Deaths: {record.deaths === null || record.deaths === undefined ? 'Unknown' : fmt(record.deaths)}</Text>
              <Text style={styles.muted}>Validation: {record.source_validation_status || 'Not specified'} · {record.source_validation_note || 'No validation note'}</Text>
              {!!record.source_url && /^https:\/\/(?:www\.)?ncdc\.mohfw\.gov\.in\//i.test(String(record.source_url)) && <Pressable onPress={() => Linking.openURL(String(record.source_url)).catch(() => {})} style={styles.sourceLink}><Text style={styles.sourceLinkText}>Open official report ↗</Text></Pressable>}
            </View>) : <View style={styles.noteCard}><Text style={styles.noteText}>No staged rows are loaded yet. Connect the reviewer token in Report review queue, then return here and refresh this screen.</Text></View>}
          </> : <View style={styles.noteCard}><Text style={styles.noteText}>For the detailed row preview, connect the reviewer token in Report review queue. It stays in memory only and is not saved to the phone.</Text></View>}
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
  brandCopy: { flex: 1, minWidth: 0 },
  eyebrow: { color: '#9CB1CA', fontSize: 9, letterSpacing: 1.5, fontWeight: '800' },
  brandTitle: { color: '#FFFFFF', fontSize: 22, fontWeight: '800', marginTop: 2, flexShrink: 1 },
  languageRow: { gap: 8, paddingTop: 14 },
  languageChip: { borderWidth: 1, borderColor: '#334762', borderRadius: 99, paddingHorizontal: 11, paddingVertical: 7 },
  languageChipActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  languageText: { fontSize: 11, color: '#D8E2EE', fontWeight: '700' },
  languageTextActive: { color: COLORS.navy },
  tabs: { flexGrow: 0, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: COLORS.border },
  tabsContent: { flexDirection: 'row', paddingHorizontal: 8 },
  tab: { flexGrow: 0, paddingHorizontal: 13, paddingVertical: 14, alignItems: 'center', borderBottomWidth: 3, borderBottomColor: 'transparent' },
  tabActive: { borderBottomColor: COLORS.teal },
  tabText: { color: COLORS.muted, fontWeight: '700', fontSize: 12, flexShrink: 1, textAlign: 'center' },
  tabTextActive: { color: COLORS.tealDark },
  liveStrip: { minHeight: 28, paddingHorizontal: 12, paddingVertical: 5, backgroundColor: '#E8F8F5', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6 },
  liveDot: { width: 7, height: 7, borderRadius: 4 },
  liveDotOn: { backgroundColor: '#13754F' },
  liveDotOff: { backgroundColor: '#C27B16' },
  liveStripText: { color: COLORS.tealDark, fontSize: 9, fontWeight: '700', flexShrink: 1 },
  liveNotice: { backgroundColor: '#FFF5DA', padding: 9, borderBottomWidth: 1, borderBottomColor: '#F0DFA9' },
  liveNoticeText: { color: '#755315', fontSize: 11, lineHeight: 16 },
  parityCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 13, padding: 13, gap: 6 },
  metricInline: { color: COLORS.tealDark, fontSize: 12, fontWeight: '900' },
  filterLabel: { color: COLORS.text, fontSize: 12, fontWeight: '800', marginBottom: 6 },
  componentChoices: { flexDirection: 'row', gap: 7 },
  componentChip: { paddingHorizontal: 13, paddingVertical: 8, borderRadius: 9, borderWidth: 1, borderColor: COLORS.border, backgroundColor: '#FFFFFF' },
  componentChipActive: { backgroundColor: COLORS.navy, borderColor: COLORS.navy },
  componentChipText: { color: COLORS.text, fontWeight: '800' },
  componentChipTextActive: { color: '#FFFFFF' },
  content: { padding: 16, paddingBottom: 32, gap: 14 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  sectionKicker: { color: COLORS.tealDark, fontWeight: '800', letterSpacing: 1.2, fontSize: 9, marginBottom: 5 },
  sectionTitle: { color: COLORS.text, fontWeight: '900', fontSize: 23, marginBottom: 6, flexShrink: 1 },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  statCard: { width: '48%', flexGrow: 1, minWidth: 135, backgroundColor: COLORS.card, padding: 15, borderRadius: 15, borderWidth: 1, borderColor: COLORS.border, minHeight: 98, justifyContent: 'space-between' },
  statCardAccent: { backgroundColor: COLORS.navy, borderColor: COLORS.navy },
  statLabel: { color: COLORS.muted, fontSize: 12, fontWeight: '700', flexShrink: 1 },
  statLabelAccent: { color: '#B9CADC' },
  statValue: { color: COLORS.text, fontSize: 26, fontWeight: '900', marginTop: 11, flexShrink: 1 },
  statValueAccent: { color: '#FFFFFF' },
  button: { backgroundColor: COLORS.tealDark, paddingVertical: 12, paddingHorizontal: 16, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  buttonSecondary: { backgroundColor: '#FFFFFF', borderColor: COLORS.border, borderWidth: 1 },
  buttonDisabled: { opacity: 0.55 },
  buttonPressed: { opacity: 0.82 },
  buttonText: { color: '#FFFFFF', fontWeight: '800', fontSize: 13, flexShrink: 1, textAlign: 'center' },
  buttonTextSecondary: { color: COLORS.text },
  icaPeriod: { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 8, gap: 6 },
  icaPeriodTitle: { color: COLORS.text, fontSize: 11, fontWeight: '900', flexShrink: 1 },
  icaSignalRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  icaSignalName: { color: COLORS.muted, fontSize: 10, fontWeight: '800', width: 30 },
  icaAxis: { flex: 1, minWidth: 20, height: 10, backgroundColor: '#E6EDF4', borderRadius: 99, overflow: 'hidden', position: 'relative' },
  icaAxisCenter: { position: 'absolute', zIndex: 2, left: '50%', top: 0, bottom: 0, width: 1, backgroundColor: '#7C8AA0' },
  icaPositive: { position: 'absolute', top: 0, bottom: 0, backgroundColor: COLORS.tealDark },
  icaNegative: { position: 'absolute', top: 0, bottom: 0, backgroundColor: '#B6402C' },
  icaSignalValue: { color: COLORS.text, fontSize: 10, fontWeight: '800', width: 38, textAlign: 'right' },
  chartCard: { backgroundColor: '#FFFFFF', borderColor: COLORS.border, borderWidth: 1, borderRadius: 15, padding: 14, gap: 9, minWidth: 0 },
  chartHead: { gap: 4 },
  chartTitle: { color: COLORS.text, fontSize: 15, fontWeight: '900', flexShrink: 1 },
  chartCaption: { color: COLORS.muted, fontSize: 10, lineHeight: 15, flexShrink: 1 },
  chartEmpty: { color: COLORS.muted, fontSize: 12, lineHeight: 18 },
  weeklyChartBars: { flexDirection: 'row', alignItems: 'flex-end', gap: 10, paddingVertical: 5, paddingHorizontal: 2 },
  weeklyChartColumn: { width: 48, alignItems: 'center', gap: 5 },
  weeklyChartValue: { color: COLORS.text, fontSize: 10, fontWeight: '800', maxWidth: 48 },
  weeklyChartArea: { width: 29, height: 92, justifyContent: 'flex-end', alignItems: 'center', backgroundColor: '#F0F4F8', borderRadius: 6, overflow: 'hidden' },
  weeklyChartBar: { width: 21, backgroundColor: COLORS.tealDark, borderTopLeftRadius: 5, borderTopRightRadius: 5 },
  weeklyChartLabel: { color: COLORS.muted, fontSize: 9, fontWeight: '700', maxWidth: 48 },
  rankRow: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0 },
  rankLabel: { color: COLORS.text, fontSize: 11, width: 95, flexShrink: 1 },
  rankTrack: { flex: 1, minWidth: 25, height: 9, borderRadius: 99, backgroundColor: '#E6EDF4', overflow: 'hidden' },
  rankFill: { height: '100%', borderRadius: 99, backgroundColor: COLORS.tealDark },
  rankValue: { width: 54, textAlign: 'right', color: COLORS.text, fontSize: 11, fontWeight: '800' },
  noteCard: { backgroundColor: COLORS.pale, borderRadius: 13, padding: 14, gap: 7 },
  noteTitle: { color: COLORS.tealDark, fontSize: 10, letterSpacing: 1.1, fontWeight: '900' },
  noteText: { color: COLORS.muted, fontSize: 12, lineHeight: 18, marginTop: 7, flexShrink: 1 },
  loading: { minHeight: 150, alignItems: 'center', justifyContent: 'center', gap: 12 },
  muted: { color: COLORS.muted, fontSize: 12, lineHeight: 18, flexShrink: 1 },
  errorBox: { padding: 14, gap: 10, backgroundColor: COLORS.redPale, borderRadius: 12 },
  errorText: { color: COLORS.red, fontSize: 12, lineHeight: 18 },
  bodyCopy: { color: COLORS.muted, fontSize: 12, lineHeight: 19, marginBottom: 4, flexShrink: 1 },
  promptList: { gap: 8 },
  promptChip: { alignSelf: 'flex-start', borderRadius: 99, borderColor: COLORS.border, borderWidth: 1, backgroundColor: '#FFFFFF', paddingHorizontal: 12, paddingVertical: 9, maxWidth: '100%' },
  promptText: { color: COLORS.text, fontSize: 12, fontWeight: '700' },
  input: { minHeight: 52, backgroundColor: '#FFFFFF', borderRadius: 12, paddingHorizontal: 14, paddingVertical: 13, borderColor: COLORS.border, borderWidth: 1, color: COLORS.text, fontSize: 14 },
  answerCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 16, padding: 15, gap: 7 },
  answerKicker: { color: COLORS.tealDark, fontSize: 9, fontWeight: '900', letterSpacing: 1.1 },
  answerText: { color: COLORS.text, fontSize: 14, lineHeight: 21, marginVertical: 4, flexShrink: 1 },
  answerMetrics: { gap: 8, marginVertical: 7 },
  answerMetric: { borderRadius: 10, backgroundColor: COLORS.page, padding: 11, gap: 4 },
  answerMetricTitle: { color: COLORS.text, fontSize: 12, fontWeight: '800' },
  sourceHeader: { color: COLORS.text, fontWeight: '900', fontSize: 10, letterSpacing: 1, marginTop: 8 },
  sourceLink: { paddingVertical: 7 },
  sourceLinkText: { color: COLORS.tealDark, fontSize: 12, fontWeight: '700', flexShrink: 1 },
  sourceCard: { backgroundColor: '#FFFFFF', borderColor: COLORS.border, borderWidth: 1, borderRadius: 14, padding: 14, gap: 7 },
  sourceTop: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 },
  sourceName: { flex: 1, color: COLORS.text, fontWeight: '800', fontSize: 14, lineHeight: 20 },
  statusBadge: { borderRadius: 99, paddingVertical: 4, paddingHorizontal: 8 },
  statusAvailable: { backgroundColor: COLORS.greenPale },
  statusUnavailable: { backgroundColor: COLORS.redPale },
  statusText: { color: COLORS.green, fontSize: 10, fontWeight: '800' },
  trendFilterRow: { flexDirection: 'row', gap: 8 },
  trendFilterInput: { flex: 1, minWidth: 0, minHeight: 46, backgroundColor: '#FFFFFF', borderRadius: 11, paddingHorizontal: 10, paddingVertical: 10, borderColor: COLORS.border, borderWidth: 1, color: COLORS.text, fontSize: 11 },
  trendActions: { flexDirection: 'row', gap: 8 },
  trendActionCell: { flex: 1, minWidth: 0 },
  trendSubheading: { color: COLORS.text, fontWeight: '900', fontSize: 17, marginTop: 3 },
  districtCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 13, padding: 13, gap: 5 },
  districtCardSelected: { borderColor: COLORS.tealDark, borderWidth: 2 },
  detailCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 15, padding: 14, gap: 10 },
  detailHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 },
  detailHeaderCopy: { flex: 1, gap: 4 },
  detailTitle: { color: COLORS.text, fontSize: 17, fontWeight: '900', flexShrink: 1 },
  detailReport: { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 10, gap: 4 },
  detailDisease: { color: COLORS.text, fontSize: 14, fontWeight: '900', flexShrink: 1 },
  detailMetrics: { color: COLORS.tealDark, fontSize: 12, fontWeight: '800' },
  districtTitleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  districtName: { color: COLORS.text, fontSize: 14, fontWeight: '900', flex: 1 },
  districtCases: { color: COLORS.tealDark, fontSize: 13, fontWeight: '900' },
  trendBarTrack: { height: 8, borderRadius: 99, backgroundColor: '#E6EDF4', overflow: 'hidden', marginTop: 5 },
  trendBar: { height: '100%', borderRadius: 99, backgroundColor: COLORS.tealDark },
  trendLatest: { color: COLORS.muted, fontSize: 10, marginTop: 3 },
  mapCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: COLORS.border, borderRadius: 15, padding: 10, gap: 9, overflow: 'hidden' },
  mapLegendRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, justifyContent: 'space-between' },
  mapLegendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  mapLegendSwatch: { width: 11, height: 11, borderRadius: 3 },
  mapLegendText: { color: COLORS.muted, fontSize: 9, fontWeight: '700', flexShrink: 1 },
  reviewFactsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  reviewFact: { color: COLORS.text, fontSize: 11, lineHeight: 16, flexShrink: 1, flex: 1, minWidth: 130 },
  reviewNoteInput: { minHeight: 70, textAlignVertical: 'top' },
  reviewStatusRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: 8, gap: 10 },
  footer: { marginTop: 18, paddingTop: 15, borderTopWidth: 1, borderTopColor: COLORS.border, gap: 3 },
  footerText: { fontSize: 10, color: '#8290A2', lineHeight: 15, flexShrink: 1 },
  loginContent: { flexGrow: 1, justifyContent: 'center', padding: 22, backgroundColor: COLORS.page },
  loginCard: { backgroundColor: COLORS.card, borderColor: COLORS.border, borderWidth: 1, borderRadius: 20, padding: 22, gap: 12 },
  loginBrandRow: { alignItems: 'center', gap: 9, marginBottom: 2 },
  loginEyebrow: { color: COLORS.tealDark, fontSize: 9, fontWeight: '900', letterSpacing: 1.4, textAlign: 'center' },
  loginTitle: { color: COLORS.text, fontWeight: '900', fontSize: 25, textAlign: 'center' },
  loginHint: { color: COLORS.muted, fontSize: 13, lineHeight: 19, textAlign: 'center', marginBottom: 8 },
  loginLabel: { color: COLORS.text, fontSize: 12, fontWeight: '800', marginBottom: -7 },
  loginInput: { minHeight: 48, backgroundColor: '#FFFFFF', borderRadius: 11, paddingHorizontal: 13, paddingVertical: 11, borderColor: COLORS.border, borderWidth: 1, color: COLORS.text, fontSize: 14 },
  loginFootnote: { color: COLORS.muted, fontSize: 10, lineHeight: 15, marginTop: 4 },
  signOutButton: { alignSelf: 'flex-end', paddingHorizontal: 11, paddingVertical: 7, borderWidth: 1, borderColor: '#334762', borderRadius: 99, marginTop: 10 },
  signOutText: { color: '#FFFFFF', fontWeight: '800', fontSize: 11 },
});
