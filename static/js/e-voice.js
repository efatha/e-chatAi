const startRecordBtn = document.getElementById('start-record');
const messageInput = document.getElementById('message-input');
const composerForm = messageInput.closest('form');
const messageTrack = document.querySelector('.voice-message-track');
messageTrack.replaceChildren();
const TRACK_BARS = 36;
for (let index = 0; index < TRACK_BARS; index += 1) {
  const bar = document.createElement('span');
  bar.style.animationDelay = `${(index % 8) * 0.07}s`;
  messageTrack.appendChild(bar);
}
const trackBars = messageTrack.querySelectorAll('span');
const iconBars = startRecordBtn.querySelectorAll('.voice-live i');

iconBars.forEach((bar, index) => {
  bar.style.animationDelay = `${index * 0.1}s`;
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SpeechRecognition) {
  startRecordBtn.disabled = true;
  startRecordBtn.title = 'Voice input not supported on this browser.';
  startRecordBtn.setAttribute('aria-label', 'Voice input not supported on this browser.');
} else {
  const recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = true;

  let finalTranscript = '';
  let listening = false;
  let audioContext = null;
  let analyser = null;
  let mediaStream = null;
  let frameId = 0;
  const messageLevels = new Array(trackBars.length).fill(0.16);

  const setListening = (on) => {
    listening = on;
    startRecordBtn.classList.toggle('is-listening', on);
    composerForm.classList.toggle('is-recording', on);
    startRecordBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    startRecordBtn.title = on ? 'Stop voice input' : 'Start voice input';
    startRecordBtn.setAttribute('aria-label', startRecordBtn.title);
    if (!on) {
      startRecordBtn.classList.remove('has-levels');
      composerForm.classList.remove('has-levels');
    }
  };

  const paintTrack = (level) => {
    messageLevels.push(Math.max(0.16, Math.min(1, level)));
    if (messageLevels.length > trackBars.length) messageLevels.shift();
    trackBars.forEach((bar, index) => {
      bar.style.transform = `scaleY(${messageLevels[index]})`;
    });
  };

  const stopLevels = () => {
    cancelAnimationFrame(frameId);
    frameId = 0;
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    if (audioContext) audioContext.close();
    audioContext = null;
    analyser = null;
    messageLevels.fill(0.16);
  };

  const startLevels = () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      if (!listening) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStream = stream;
      audioContext = new AudioContext();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      let frame = 0;
      startRecordBtn.classList.add('has-levels');
      composerForm.classList.add('has-levels');
      const tick = () => {
        if (!analyser) return;
        analyser.getByteTimeDomainData(samples);
        let energy = 0;
        for (let i = 0; i < samples.length; i += 1) {
          const sample = (samples[i] - 128) / 128;
          energy += sample * sample;
        }
        const level = Math.min(1, Math.sqrt(energy / samples.length) * 3.4);
        frame += 1;
        if (frame % 4 === 0) paintTrack(0.18 + level * 0.82);
        iconBars.forEach((bar, index) => {
          const wobble = 0.55 + 0.45 * Math.sin(frame / 2.4 + index * 0.9);
          bar.style.transform = `scaleY(${0.26 + level * wobble})`;
        });
        frameId = requestAnimationFrame(tick);
      };
      tick();
    }).catch(() => {
      startRecordBtn.classList.remove('has-levels');
      composerForm.classList.remove('has-levels');
    });
  };

  startRecordBtn.addEventListener('click', () => {
    if (listening) {
      recognition.stop();
      return;
    }
    finalTranscript = '';
    messageLevels.fill(0.16);
    try {
      recognition.start();
    } catch (error) {
      console.error('Speech recognition could not start:', error);
    }
  });

  recognition.onstart = () => {
    setListening(true);
    startLevels();
  };

  recognition.onresult = (event) => {
    let interimTranscript = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalTranscript += `${transcript} `;
      else interimTranscript += transcript;
    }
    messageInput.value = finalTranscript + interimTranscript;
  };

  recognition.onend = () => {
    const spoken = finalTranscript.trim();
    setListening(false);
    stopLevels();
    if (!spoken) return;
    messageInput.value = spoken;
    document.querySelector('.send-message').click();
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    setListening(false);
    stopLevels();
  };
}
