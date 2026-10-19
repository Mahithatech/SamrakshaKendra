/* SK_MULTILINGUAL_UI_V1 — core navigation and workspace localization. */
export const UI_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'kn', label: 'ಕನ್ನಡ' },
  { code: 'hi', label: 'हिन्दी' },
];

const NAV = {
  en: {
    overview: 'Overview', history: 'Historical data', signals: 'Global signals',
    'india-reports': 'India reports', 'report-queue': 'Report review queue',
    'staging-preview': 'Staged NCDC data', anomalies: 'Anomaly detection',
    ica: 'ICA lab', map: 'Map & hotspots', assistant: 'Evidence assistant',
  },
  te: {
    overview: 'సారాంశం', history: 'చారిత్రక డేటా', signals: 'ప్రపంచ సంకేతాలు',
    'india-reports': 'భారత నివేదికలు', 'report-queue': 'నివేదిక సమీక్ష క్యూలు',
    'staging-preview': 'NCDC స్టేజింగ్ డేటా', anomalies: 'అసాధారణత గుర్తింపు',
    ica: 'ICA ల్యాబ్', map: 'మ్యాప్ & హాట్‌స్పాట్‌లు', assistant: 'సాక్ష్యాధారిత సహాయకుడు',
  },
  kn: {
    overview: 'ಅವಲೋಕನ', history: 'ಐತಿಹಾಸಿಕ ಡೇಟಾ', signals: 'ಜಾಗತಿಕ ಸೂಚನೆಗಳು',
    'india-reports': 'ಭಾರತ ವರದಿಗಳು', 'report-queue': 'ವರದಿ ಪರಿಶೀಲನಾ ಸರತಿ',
    'staging-preview': 'NCDC ಸ್ಟೇಜಿಂಗ್ ಡೇಟಾ', anomalies: 'ಅಸಾಮಾನ್ಯತೆ ಪತ್ತೆ',
    ica: 'ICA ಪ್ರಯೋಗಾಲಯ', map: 'ನಕ್ಷೆ ಮತ್ತು ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು', assistant: 'ಸಾಕ್ಷ್ಯಾಧಾರಿತ ಸಹಾಯಕ',
  },
  hi: {
    overview: 'अवलोकन', history: 'ऐतिहासिक डेटा', signals: 'वैश्विक संकेत',
    'india-reports': 'भारत रिपोर्ट', 'report-queue': 'रिपोर्ट समीक्षा कतार',
    'staging-preview': 'NCDC स्टेजिंग डेटा', anomalies: 'विसंगति पहचान',
    ica: 'ICA प्रयोगशाला', map: 'मानचित्र और हॉटस्पॉट', assistant: 'साक्ष्य-आधारित सहायक',
  },
};

const TEXT = {
  'Public health overview': {
    te: 'ప్రజారోగ్య అవలోకనం', kn: 'ಸಾರ್ವಜನಿಕ ಆರೋಗ್ಯ ಅವಲೋಕನ', hi: 'सार्वजनिक स्वास्थ्य अवलोकन',
  },
  'Understand available surveillance data and recent signals.': {
    te: 'అందుబాటులో ఉన్న నిఘా డేటా మరియు ఇటీవలి సంకేతాలను పరిశీలించండి.',
    kn: 'ಲಭ್ಯವಿರುವ ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾ ಮತ್ತು ಇತ್ತೀಚಿನ ಸೂಚನೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.',
    hi: 'उपलब्ध निगरानी डेटा और हाल के संकेतों को समझें।',
  },
  'WORKSPACE': { te: 'పని ప్రదేశం', kn: 'ಕಾರ್ಯಕ್ಷೇತ್ರ', hi: 'कार्यस्थल' },
  'Reset filters': { te: 'ఫిల్టర్లను రీసెట్ చేయండి', kn: 'ಫಿಲ್ಟರ್ ಮರುಹೊಂದಿಸಿ', hi: 'फ़िल्टर रीसेट करें' },
  'Clear all data filters': { te: 'అన్ని డేటా ఫిల్టర్లను తొలగించండి', kn: 'ಎಲ್ಲಾ ಡೇಟಾ ಫಿಲ್ಟರ್‌ಗಳನ್ನು ತೆರವುಗೊಳಿಸಿ', hi: 'सभी डेटा फ़िल्टर साफ़ करें' },
  'LIVE STREAM ON': { te: 'లైవ్ స్ట్రీమ్ ఆన్', kn: 'ಲೈವ್ ಸ್ಟ್ರೀಮ್ ಆನ್', hi: 'लाइव स्ट्रीम चालू' },
  'Live alerts connected': { te: 'లైవ్ అలర్ట్‌లు కనెక్ట్ అయ్యాయి', kn: 'ಲೈವ್ ಎಚ್ಚರಿಕೆಗಳು ಸಂಪರ್ಕಗೊಂಡಿವೆ', hi: 'लाइव अलर्ट जुड़े हैं' },
  'Connecting live alerts…': { te: 'లైవ్ అలర్ట్‌లకు కనెక్ట్ అవుతోంది…', kn: 'ಲೈವ್ ಎಚ್ಚರಿಕೆಗಳಿಗೆ ಸಂಪರ್ಕಿಸಲಾಗುತ್ತಿದೆ…', hi: 'लाइव अलर्ट से जुड़ रहा है…' },
  'Live alerts offline': { te: 'లైవ్ అలర్ట్‌లు ఆఫ్‌లైన్‌లో ఉన్నాయి', kn: 'ಲೈವ್ ಎಚ್ಚರಿಕೆಗಳು ಆಫ್‌ಲೈನ್‌ನಲ್ಲಿವೆ', hi: 'लाइव अलर्ट ऑफ़लाइन हैं' },
  'Surveillance records': { te: 'నిఘా రికార్డులు', kn: 'ಮೇಲ್ವಿಚಾರಣಾ ದಾಖಲೆಗಳು', hi: 'निगरानी रिकॉर्ड' },
  'Reported cases': { te: 'నివేదించిన కేసులు', kn: 'ವರದಿಯಾದ ಪ್ರಕರಣಗಳು', hi: 'रिपोर्ट किए गए मामले' },
  'Reported deaths': { te: 'నివేదించిన మరణాలు', kn: 'ವರದಿಯಾದ ಸಾವುಗಳು', hi: 'रिपोर्ट की गई मौतें' },
  'States / UTs': { te: 'రాష్ట్రాలు / కేంద్రపాలిత ప్రాంతాలు', kn: 'ರಾಜ್ಯಗಳು / ಕೇಂದ್ರಾಡಳಿತ ಪ್ರದೇಶಗಳು', hi: 'राज्य / केंद्र शासित प्रदेश' },
  'At a glance': { te: 'ఒక చూపులో', kn: 'ಒಂದು ನೋಟದಲ್ಲಿ', hi: 'एक नज़र में' },
  'LIVE OFFICIAL SOURCE UPDATES': { te: 'అధికారిక మూలాల తాజా సమాచారం', kn: 'ಅಧಿಕೃತ ಮೂಲಗಳ ನವೀಕರಣಗಳು', hi: 'आधिकारिक स्रोत अपडेट' },
  'Latest published outbreak intelligence': { te: 'తాజా ప్రచురిత వ్యాధి వ్యాప్తి సమాచారం', kn: 'ಇತ್ತೀಚಿನ ಪ್ರಕಟಿತ ರೋಗ ಹರಡುವಿಕೆ ಮಾಹಿತಿ', hi: 'नवीनतम प्रकाशित प्रकोप जानकारी' },
  'IDSP DATA EXPLORER': { te: 'IDSP డేటా ఎక్స్‌ప్లోరర్', kn: 'IDSP ಡೇಟಾ ಅನ್ವೇಷಣೆ', hi: 'IDSP डेटा एक्सप्लोरर' },
  'Evidence-led monitoring.': { te: 'ఆధారాలపై ఆధారిత పర్యవేక్షణ.', kn: 'ಸಾಕ್ಷ್ಯಾಧಾರಿತ ಮೇಲ್ವಿಚಾರಣೆ.', hi: 'साक्ष्य-आधारित निगरानी।' },
  'Earlier signals.': { te: 'ముందస్తు సంకేతాలు.', kn: 'ಮುಂಚಿನ ಸೂಚನೆಗಳು.', hi: 'पहले मिलने वाले संकेत।' },
  'A shared workspace to inspect historical reports, investigate possible anomalies and demonstrate real-time alert delivery.': { te: 'చారిత్రక నివేదికలను పరిశీలించడానికి, అసాధారణ ధోరణులను అధ్యయనం చేయడానికి మరియు రియల్-టైమ్ అలర్ట్‌లను ప్రదర్శించడానికి ఒకే వేదిక.', kn: 'ಐತಿಹಾಸಿಕ ವರದಿಗಳನ್ನು ಪರಿಶೀಲಿಸಲು, ಅಸಾಮಾನ್ಯ ಮಾದರಿಗಳನ್ನು ಅಧ್ಯಯನ ಮಾಡಲು ಮತ್ತು ತಕ್ಷಣದ ಎಚ್ಚರಿಕೆಗಳನ್ನು ಪ್ರದರ್ಶಿಸಲು ಒಂದೇ ಕಾರ್ಯಕ್ಷೇತ್ರ.', hi: 'ऐतिहासिक रिपोर्ट देखने, संभावित विसंगतियों की जाँच करने और रीयल-टाइम अलर्ट दिखाने के लिए साझा कार्यक्षेत्र।' },
  'Explore historical data': { te: 'చారిత్రక డేటాను పరిశీలించండి', kn: 'ಐತಿಹಾಸಿಕ ಡೇಟಾವನ್ನು ಅನ್ವೇಷಿಸಿ', hi: 'ऐतिहासिक डेटा देखें' },
  'Open anomaly lab': { te: 'అసాధారణత ల్యాబ్ తెరవండి', kn: 'ಅಸಾಮಾನ್ಯತೆ ಪ್ರಯೋಗಾಲಯ ತೆರೆಯಿರಿ', hi: 'विसंगति लैब खोलें' },
  'MONITORING': { te: 'పర్యవేక్షణ', kn: 'ಮೇಲ್ವಿಚಾರಣೆ', hi: 'निगरानी' },
  'DATA': { te: 'డేటా', kn: 'ಡೇಟಾ', hi: 'डेटा' },
  'SIGNALS': { te: 'సంకేతాలు', kn: 'ಸೂಚನೆಗಳು', hi: 'संकेत' },
  'INSIGHTS': { te: 'అంతర్దృష్టులు', kn: 'ಒಳನೋಟಗಳು', hi: 'जानकारी' },
  'CURRENT DATASET': { te: 'ప్రస్తుత డేటాసెట్', kn: 'ಪ್ರಸ್ತುತ ಡೇಟಾಸೆಟ್', hi: 'वर्तमान डेटासेट' },
  'Values reflect records loaded into this installation': { te: 'ఈ ఇన్‌స్టాలేషన్‌లో లోడ్ చేసిన రికార్డుల ఆధారంగా విలువలు చూపబడతాయి', kn: 'ಈ ಸ್ಥಾಪನೆಯಲ್ಲಿ ಲೋಡ್ ಮಾಡಿದ ದಾಖಲೆಗಳ ಮೌಲ್ಯಗಳು', hi: 'मान इस इंस्टॉलेशन में लोड रिकॉर्ड पर आधारित हैं' },
  'Available aggregate records': { te: 'అందుబాటులో ఉన్న సమగ్ర రికార్డులు', kn: 'ಲಭ್ಯವಿರುವ ಒಟ್ಟು ದಾಖಲೆಗಳು', hi: 'उपलब्ध समेकित रिकॉर्ड' },
  'Sum of available case counts': { te: 'అందుబాటులో ఉన్న కేసుల మొత్తం', kn: 'ಲಭ್ಯವಿರುವ ಪ್ರಕರಣಗಳ ಮೊತ್ತ', hi: 'उपलब्ध मामलों का कुल योग' },
  'Sum of available death counts': { te: 'అందుబాటులో ఉన్న మరణాల మొత్తం', kn: 'ಲಭ್ಯವಿರುವ ಸಾವುಗಳ ಮೊತ್ತ', hi: 'उपलब्ध मौतों का कुल योग' },
  'distinct disease labels': { te: 'విభిన్న వ్యాధి పేర్లు', kn: 'ವಿಭಿನ್ನ ರೋಗದ ಹೆಸರುಗಳು', hi: 'अलग-अलग रोग नाम' },
  'TIME SERIES': { te: 'కాల శ్రేణి', kn: 'ಕಾಲ ಸರಣಿ', hi: 'समय श्रृंखला' },
  'Reported cases by reporting week': { te: 'నివేదిక వారాల వారీగా కేసులు', kn: 'ವರದಿ ವಾರದ ಪ್ರಕಾರ ಪ್ರಕರಣಗಳು', hi: 'रिपोर्टिंग सप्ताह के अनुसार मामले' },
  'Historical': { te: 'చారిత్రక', kn: 'ಐತಿಹಾಸಿಕ', hi: 'ऐतिहासिक' },
  'GEOGRAPHY': { te: 'భౌగోళికం', kn: 'ಭೌಗೋಳಿಕತೆ', hi: 'भूगोल' },
  'Top reported states': { te: 'అత్యధిక నివేదికలున్న రాష్ట్రాలు', kn: 'ಅತ್ಯಧಿಕ ವರದಿಯ ರಾಜ್ಯಗಳು', hi: 'सबसे अधिक रिपोर्ट वाले राज्य' },
  'DISEASE BREAKDOWN': { te: 'వ్యాధుల విభజన', kn: 'ರೋಗಗಳ ವಿವರ', hi: 'रोग विवरण' },
  'Most reported diseases': { te: 'అత్యధికంగా నివేదించిన వ్యాధులు', kn: 'ಹೆಚ್ಚು ವರದಿಯಾದ ರೋಗಗಳು', hi: 'सबसे अधिक रिपोर्ट की गई बीमारियाँ' },
  'View data →': { te: 'డేటా చూడండి →', kn: 'ಡೇಟಾ ವೀಕ್ಷಿಸಿ →', hi: 'डेटा देखें →' },
  'EVENT STREAM': { te: 'ఈవెంట్ స్ట్రీమ్', kn: 'ಈವೆಂಟ್ ಸ್ಟ್ರೀಮ್', hi: 'इवेंट स्ट्रीम' },
  'Live alert activity': { te: 'లైవ్ అలర్ట్ కార్యకలాపాలు', kn: 'ಲೈವ್ ಎಚ್ಚರಿಕೆ ಚಟುವಟಿಕೆ', hi: 'लाइव अलर्ट गतिविधि' },
  'No new live events': { te: 'కొత్త లైవ్ ఈవెంట్‌లు లేవు', kn: 'ಹೊಸ ಲೈವ್ ಘಟನೆಗಳಿಲ್ಲ', hi: 'कोई नई लाइव घटना नहीं' },
  'Keep this page open, then trigger a synthetic demo event from the Anomaly detection page.': { te: 'ఈ పేజీని తెరిచి ఉంచి, అసాధారణత గుర్తింపు పేజీ నుంచి డెమో ఈవెంట్‌ను ప్రారంభించండి.', kn: 'ಈ ಪುಟವನ್ನು ತೆರೆದಿಟ್ಟು, ಅಸಾಮಾನ್ಯತೆ ಪತ್ತೆ ಪುಟದಿಂದ ಡೆಮೊ ಈವೆಂಟ್ ಪ್ರಾರಂಭಿಸಿ.', hi: 'इस पेज को खुला रखें और विसंगति पहचान पेज से डेमो इवेंट चलाएँ।' },
  'Test live notification': { te: 'లైవ్ నోటిఫికేషన్ పరీక్షించండి', kn: 'ಲೈವ್ ಅಧಿಸೂಚನೆ ಪರೀಕ್ಷಿಸಿ', hi: 'लाइव सूचना जाँचें' },
};

export function translateNav(language, id, fallback = id) {
  const lang = NAV[language] ? language : 'en';
  return NAV[lang][id] || fallback || NAV.en[id] || id;
}

export function translateText(language, text) {
  const lang = TEXT[text]?.[language];
  return lang || text;
}
