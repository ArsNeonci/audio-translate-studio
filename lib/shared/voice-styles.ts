// Mirrors worker/audio_translate/tts/voice_styles.py; labels are uiText keys.
export const voiceStyles = [
  {id: "default", label: "Mặc định", description: "voiceStyleDefault"},
  {id: "drama", label: "Drama", description: "voiceStyleDrama"},
  {id: "survival", label: "Sinh tồn", description: "voiceStyleSurvival"},
  {id: "rebirth", label: "Trọng sinh", description: "voiceStyleRebirth"},
] as const;
export type VoiceStyle = typeof voiceStyles[number]["id"];
export const isVoiceStyle = (value: unknown): value is VoiceStyle => voiceStyles.some(style => style.id === value);
