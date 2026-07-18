/**
 * UI-chrome translations for the assistant screen.
 *
 * Only interface text lives here: the suggested-question chips and the static labels
 * around the conversation. Every ANSWER is generated live by the backend agent in the
 * officer's chosen language -- there are deliberately no canned answers, traces or
 * action translations in this file (they used to be, purely to prototype the UI).
 */
import type { ScenarioPrompt } from "./scenarios";
import type { AssistantLanguage } from "../lib/assistantTypes";

type Translation = { label: string; prompt: string };

const PROMPT_TRANSLATIONS: Record<string, { hi: Translation; kn: Translation }> = {
  "s1-timeline": {
    hi: { label: "टाइमलाइन बनाएं", prompt: "इस केस का सार बताइए और घटनाओं व ट्रांसफ़र की समयरेखा दिखाइए।" },
    kn: { label: "ಕಾಲರೇಖೆ ತೋರಿಸಿ", prompt: "ಈ ಕೇಸ್‌ನ ಸಾರಾಂಶ ನೀಡಿ ಮತ್ತು ಘಟನೆಗಳು ಹಾಗೂ ಹಣ ವರ್ಗಾವಣೆಗಳ ಕಾಲರೇಖೆಯನ್ನು ತೋರಿಸಿ." },
  },
  "s1-money-speed": {
    hi: { label: "पैसे की गति", prompt: "पैसा कहाँ गया और खातों के बीच कितनी तेजी से चला?" },
    kn: { label: "ಹಣದ ಹರಿವು", prompt: "ಹಣ ಎಲ್ಲಿ ಹೋಯಿತು ಮತ್ತು ಖಾತೆಗಳ ನಡುವೆ ಎಷ್ಟು ವೇಗವಾಗಿ ಹರಿಯಿತು?" },
  },
  "s1-similar-mo": {
    hi: { label: "समान पैटर्न", prompt: "क्या ऐसा modus operandi कर्नाटक के दूसरे जिलों में भी दिखा है?" },
    kn: { label: "ಸಮಾನ ಮಾದರಿ", prompt: "ಇದೇ ಮೋಸ ವಿಧಾನ ಕर्नಾಟಕದ ಇತರೆ ಜಿಲ್ಲೆಗಳಲ್ಲಿಯೂ ಕಂಡಿದೆಯೇ?" },
  },
  "s1-links": {
    hi: { label: "लिंक खोजें", prompt: "संबंधित केसों में साझा खाते या डिवाइस दिखाइए।" },
    kn: { label: "ಸಂಬಂಧ ಕೊಂಡಿಗಳು", prompt: "ಸಂಬಂಧಿತ ಕೇಸ್‌ಗಳಲ್ಲಿ ಹಂಚಿಕೆಯ ಖಾತೆಗಳು ಅಥವಾ ಡಿವೈಸ್‌ಗಳನ್ನು ತೋರಿಸಿ." },
  },
  "s1-legal-gaps": {
    hi: { label: "कानूनी गैप", prompt: "अभी अभियोजन के लिए क्या तैयार है और कौन-से साक्ष्य गैप बाकी हैं?" },
    kn: { label: "ಕಾನೂನು ಕೊರತೆ", prompt: "ಈಗ ಪ್ರಾಸಿಕ್ಯೂಷನ್‌ಗೆ ಏನು ಸಿದ್ಧವಾಗಿದೆ ಮತ್ತು ಯಾವ ಸಾಕ್ಷ್ಯ ಕೊರತೆಗಳು ಉಳಿದಿವೆ?" },
  },
  "s2-known-accused": {
    hi: { label: "पहले से ज्ञात आरोपी?", prompt: "क्या यह आरोपी दूसरे नामों या पहचानों में पहले से दर्ज है?" },
    kn: { label: "ಹಿಂದೇ ದಾಖಲಾಗಿದೆಯೇ?", prompt: "ಈ ಆರೋಪಿಯು ಬೇರೆ ಹೆಸರು ಅಥವಾ ಗುರುತುಗಳಿಂದ ಈಗಾಗಲೇ ದಾಖಲಾಗಿದೆಯೇ?" },
  },
  "s2-alias-collapse": {
    hi: { label: "उपनाम मर्ज", prompt: "उपनाम समाधान के प्रमाण और confidence factors दिखाइए।" },
    kn: { label: "ಅಲಿಯಾಸ್ ಮರ್ಜ್", prompt: "ಅಲಿಯಾಸ್ ರೆಸಲ್ಯೂಷನ್ ಸಾಕ್ಷ್ಯ ಮತ್ತು ವಿಶ್ವಾಸ ಅಂಶಗಳನ್ನು ತೋರಿಸಿ." },
  },
  "s2-escalation": {
    hi: { label: "एस्केलेशन इतिहास", prompt: "अपराधी का टाइमलाइन और रकम/गंभीरता में बढ़ोतरी दिखाइए।" },
    kn: { label: "ಎಸ್ಕಲೇಶನ್ ಇತಿಹಾಸ", prompt: "ಅಪರಾಧಿಯ ಕಾಲರೇಖೆ ಮತ್ತು ಮೊತ್ತ/ತೀವ್ರತೆಯ ಏರಿಕೆ ತೋರಿಸಿ." },
  },
  "s2-cdr-update": {
    hi: { label: "CDR अपडेट", prompt: "नए CDR और अकाउंट साक्ष्य जोड़कर नेटवर्क दृश्य अपडेट कीजिए।" },
    kn: { label: "CDR ನವೀಕರಣ", prompt: "ಹೊಸ CDR ಮತ್ತು ಖಾತೆ ಸಾಕ್ಷ್ಯ ಸೇರಿಸಿ ನೆಟ್‌ವರ್ಕ್ ದೃಶ್ಯವನ್ನು ನವೀಕರಿಸಿ." },
  },
  "s2-intent-gap": {
    hi: { label: "इरादा साबित करना", prompt: "BNS 318 के तहत प्रारंभिक धोखाधड़ी-इरादा सिद्ध करने में क्या कमी है?" },
    kn: { label: "ಉದ್ದೇಶ ಸಾಬೀತು", prompt: "BNS 318 ಅಡಿಯಲ್ಲಿ ಆರಂಭಿಕ ಮೋಸದ ಉದ್ದೇಶ ಸಾಬೀತು ಮಾಡಲು ಏನು ಕೊರತೆಯಿದೆ?" },
  },
  "s3-trace": {
    hi: { label: "मनी ट्रेस", prompt: "पैसे का पूरा रास्ता ट्रेस कीजिए और अभी फ्रीज़ हो सकने वाली राशि बताइए।" },
    kn: { label: "ಹಣದ ಟ್ರೇಸ್", prompt: "ಹಣದ ಸಂಪೂರ್ಣ ಮಾರ್ಗ ಟ್ರೇಸ್ ಮಾಡಿ, ಈಗಲೇ ಫ್ರೀಜ್ ಮಾಡಬಹುದಾದ ಮೊತ್ತ ತೋರಿಸಿ." },
  },
  "s3-bridge": {
    hi: { label: "ब्रिज अकाउंट", prompt: "दूसरे अपराधों से जुड़े म्यूल खातों की पहचान कीजिए।" },
    kn: { label: "ಬ್ರಿಜ್ ಖಾತೆ", prompt: "ಇತರೆ ಅಪರಾಧಗಳಿಗೆ ಸಂಪರ್ಕ ಹೊಂದಿರುವ ಮ್ಯೂಲ್ ಖಾತೆಗಳನ್ನು ಗುರುತಿಸಿ." },
  },
  "s3-ledger-kyc": {
    hi: { label: "लेजर + KYC", prompt: "बैंक लेजर और KYC प्रोसेस करके हब खातों को रैंक कीजिए।" },
    kn: { label: "ಲೆಡ್ಜರ್ + KYC", prompt: "ಬ್ಯಾಂಕ್ ಲೆಡ್ಜರ್ ಮತ್ತು KYC ಪ್ರಕ್ರಿಯೆ ಮಾಡಿ ಹಬ್ ಖಾತೆಗಳನ್ನು ರ್ಯಾಂಕ್ ಮಾಡಿ." },
  },
  "s3-pmla": {
    hi: { label: "PMLA तैयारी", prompt: "क्या अभी मनी-लॉन्डरिंग चार्ज जोड़े जा सकते हैं? कानूनी जोखिम क्या हैं?" },
    kn: { label: "PMLA ಸಿದ್ಧತೆ", prompt: "ಈಗ ಮಣಿ ಲಾಂಡರಿಂಗ್ ಆರೋಪ ಸೇರಿಸಬಹುದೇ? ಕಾನೂನು ಅಪಾಯಗಳು ಯಾವುವು?" },
  },
  "s4-pattern": {
    hi: { label: "पैटर्न अलर्ट", prompt: "क्या यह FIR हाल के हफ्तों में उभरते स्कैम पैटर्न का हिस्सा है?" },
    kn: { label: "ಪ್ಯಾಟರ್ನ್ ಅಲರ್ಟ್", prompt: "ಈ FIR ಇತ್ತೀಚಿನ ವಾರಗಳಲ್ಲಿ ಬೆಳೆಯುತ್ತಿರುವ ಮೋಸ ಮಾದರಿಯ ಭಾಗವೇ?" },
  },
  "s4-organized": {
    hi: { label: "एक ही गैंग?", prompt: "क्या यह उछाल एक ही संगठित रिंग चला रही है या कॉपीकैट केस हैं?" },
    kn: { label: "ಒಂದು ರಿಂಗ್‌ನಾ?", prompt: "ಈ ಏರಿಕೆ ಒಂದು ಸಂಘಟಿತ ರಿಂಗ್‌ನಿಂದ ನಡೆಯುತ್ತಿದೆಯೇ ಅಥವಾ ಕಾಪಿಕ್ಯಾಟ್ ಪ್ರಕರಣಗಳೇ?" },
  },
  "s4-hotspots": {
    hi: { label: "हॉटस्पॉट और बेस", prompt: "जिला हॉटस्पॉट और shared IP से संभावित ऑपरेटर बेस दिखाइए।" },
    kn: { label: "ಹಾಟ್‌ಸ್ಪಾಟ್ ಮತ್ತು ಬೇಸ್", prompt: "ಜಿಲ್ಲಾ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು ಮತ್ತು ಹಂಚಿಕೆ IP ಆಧಾರದ ಮೇಲೆ ಆಪರೇಟರ್ ಬೇಸ್ ತೋರಿಸಿ." },
  },
  "s4-org-chart": {
    hi: { label: "ऑर्ग चार्ट", prompt: "सीज़्ड डिवाइस डेटा से ऑपरेटर संगठन-चार्ट और भूमिका मानचित्र बनाइए।" },
    kn: { label: "ಆರ್ಗ್ ಚಾರ್ಟ್", prompt: "ಸೀಜ್ ಮಾಡಿದ ಡಿವೈಸ್ ಡೇಟಾದಿಂದ ಆಪರೇಟರ್ ಸಂಘಟನೆ ಚಾರ್ಟ್ ಮತ್ತು ಪಾತ್ರ ನಕ್ಷೆ ರಚಿಸಿ." },
  },
  "s4-operator-checklist": {
    hi: { label: "ऑपरेटर लीगल चेकलिस्ट", prompt: "चार्जशीट से पहले हर ऑपरेटर के लिए साक्ष्य चेकलिस्ट क्या है?" },
    kn: { label: "ಆಪರೇಟರ್ ಕಾನೂನು ಚೆಕ್‌ಲಿಸ್ಟ್", prompt: "ಚಾರ್ಜ್‌ಶೀಟ್ ಮೊದಲು ಪ್ರತಿಯೊಬ್ಬ ಆಪರೇಟರ್‌ಗೆ ಅಗತ್ಯ ಸಾಕ್ಷ್ಯ ಚೆಕ್‌ಲಿಸ್ಟ್ ಏನು?" },
  },
};

const UI_COPY: Record<
  AssistantLanguage,
  {
    sessions: string;
    newChat: string;
    noConversationTitle: string;
    noConversationBody: string;
    freeForm: string;
    suggestedQuestions: string;
    composerPlaceholder: string;
    language: string;
    selectScenario: string;
    caseContext: string;
    showTraces: string;
    showTracesHint: string;
    traceTitle: string;
    traceSubtitle: string;
    rawMode: string;
    noTrace: string;
    traceCount: string;
    traceDemo: string;
  }
> = {
  en: {
    sessions: "Sessions",
    newChat: "New chat",
    noConversationTitle: "No conversation yet",
    noConversationBody: "Pick a scenario above to load case context, or just start typing below.",
    freeForm: "No scenario · free-form",
    suggestedQuestions: "Suggested questions",
    composerPlaceholder: "Ask about timeline, money flow, alias links, or the legal checklist…",
    language: "Language",
    selectScenario: "Select Scenario",
    caseContext: "Case / Crime context",
    showTraces: "Show traces",
    showTracesHint: "Run one assistant response to open traces",
    traceTitle: "Assistant trace",
    traceSubtitle: "Operational audit trail for this assistant run.",
    rawMode: "Show raw telemetry",
    noTrace: "No trace found for this run.",
    traceCount: "events",
    traceDemo: "Demo trace",
  },
  hi: {
    sessions: "सेशन",
    newChat: "नई चैट",
    noConversationTitle: "अभी कोई बातचीत नहीं",
    noConversationBody: "ऊपर से कोई परिदृश्य चुनें या नीचे सीधे टाइप करें।",
    freeForm: "कोई परिदृश्य नहीं · फ्री-फॉर्म",
    suggestedQuestions: "सुझाए गए प्रश्न",
    composerPlaceholder: "टाइमलाइन, मनी फ्लो, alias लिंक या कानूनी चेकलिस्ट पूछें…",
    language: "भाषा",
    selectScenario: "परिदृश्य चुनें",
    caseContext: "केस / क्राइम नंबर संदर्भ",
    showTraces: "ट्रेस देखें",
    showTracesHint: "ट्रेस खोलने के लिए पहले एक उत्तर चलाएँ",
    traceTitle: "असिस्टेंट ट्रेस",
    traceSubtitle: "इस रन का ऑपरेशनल ऑडिट ट्रेल।",
    rawMode: "रॉ टेलीमेट्री दिखाएं",
    noTrace: "इस रन के लिए ट्रेस नहीं मिला।",
    traceCount: "इवेंट",
    traceDemo: "डेमो ट्रेस",
  },
  kn: {
    sessions: "ಸೆಷನ್‌ಗಳು",
    newChat: "ಹೊಸ ಚಾಟ್",
    noConversationTitle: "ಇನ್ನೂ ಸಂಭಾಷಣೆ ಇಲ್ಲ",
    noConversationBody: "ಮೇಲೆ ಸನ್ನಿವೇಶ ಆಯ್ಕೆಮಾಡಿ ಅಥವಾ ಕೆಳಗೆ ನೇರವಾಗಿ ಬರೆಯಿರಿ.",
    freeForm: "ಸನ್ನಿವೇಶ ಇಲ್ಲ · ಫ್ರೀ-ಫಾರ್ಮ್",
    suggestedQuestions: "ಸೂಚಿಸಲಾದ ಪ್ರಶ್ನೆಗಳು",
    composerPlaceholder: "ಕಾಲರೇಖೆ, ಹಣದ ಹರಿವು, ಅಲಿಯಾಸ್ ಲಿಂಕ್ ಅಥವಾ ಕಾನೂನು ಚೆಕ್‌ಲಿಸ್ಟ್ ಬಗ್ಗೆ ಕೇಳಿ…",
    language: "ಭಾಷೆ",
    selectScenario: "ಸನ್ನಿವೇಶ ಆಯ್ಕೆಮಾಡಿ",
    caseContext: "ಕೇಸ್ / ಕ್ರೈಂ ಸಂಖ್ಯೆ ಸಂದರ್ಭ",
    showTraces: "ಟ್ರೇಸ್ ತೋರಿಸಿ",
    showTracesHint: "ಟ್ರೇಸ್ ತೆರೆಯಲು ಮೊದಲು ಒಂದು ಉತ್ತರ ರನ್ ಮಾಡಿ",
    traceTitle: "ಅಸಿಸ್ಟಂಟ್ ಟ್ರೇಸ್",
    traceSubtitle: "ಈ ರನ್‌ಗೆ ಸಂಬಂಧಿಸಿದ ಕಾರ್ಯಾಚರಣಾ ಆಡಿಟ್ ಟ್ರೇಲ್.",
    rawMode: "ರಾ ಟೆಲಿಮೆಟ್ರಿ ತೋರಿಸಿ",
    noTrace: "ಈ ರನ್‌ಗೆ ಟ್ರೇಸ್ ಸಿಗಲಿಲ್ಲ.",
    traceCount: "ಈವೆಂಟ್‌ಗಳು",
    traceDemo: "ಡೆಮೋ ಟ್ರೇಸ್",
  },
};

export function localizePrompt(prompt: ScenarioPrompt, language: AssistantLanguage): ScenarioPrompt {
  if (language === "en") return prompt;
  const translated = PROMPT_TRANSLATIONS[prompt.id]?.[language];
  if (!translated) return prompt;
  return { ...prompt, label: translated.label, prompt: translated.prompt };
}

export function uiText(language: AssistantLanguage) {
  return UI_COPY[language];
}
