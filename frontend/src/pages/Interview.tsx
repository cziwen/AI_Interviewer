import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { buildRealtimeWsUrl, getInterview, completeInterview } from '../api';
import type { Interview } from '../types';

const NO_RESPONSE_REASK_MS = 18000;
const USER_SPEECH_RMS_THRESHOLD = 0.015;

const VolumeBar: React.FC<{ level: number; isActive: boolean }> = ({ level, isActive }) => {
  if (!isActive) return null;
  
  return (
    <div style={{ 
      display: 'inline-block',
      width: '120px', 
      height: '8px', 
      backgroundColor: '#eee', 
      marginLeft: '15px', 
      borderRadius: '4px',
      overflow: 'hidden',
      verticalAlign: 'middle'
    }}>
      <div style={{ 
        width: `${Math.min(100, level * 500)}%`, 
        height: '100%', 
        backgroundColor: level > 0.03 ? '#28a745' : '#ffc107',
        transition: 'width 0.05s linear'
      }} />
    </div>
  );
};

const InterviewPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [transcript, setTranscript] = useState<string>('');
  const [isFinishing, setIsFinishing] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number>(0);
  
  // Device selection states
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicrophone, setSelectedMicrophone] = useState<string>('');
  const [selectedSpeaker, setSelectedSpeaker] = useState<string>('');
  const [showDeviceSelection, setShowDeviceSelection] = useState(true);
  
  // Volume visualization
  const [volume, setVolume] = useState<number>(0);
  const [testMicVolume, setTestMicVolume] = useState<number>(0);
  const [testSpeakerVolume, setTestSpeakerVolume] = useState<number>(0);
  const [isTestingMic, setIsTestingMic] = useState(false);
  const [isTestingSpeaker, setIsTestingSpeaker] = useState(false);

  // Agent speaking state for half-duplex strategy
  const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
  const isAgentSpeakingRef = useRef(false);

  // Gates for opening and closing
  const [hasReceivedFirstAiResponse, setHasReceivedFirstAiResponse] = useState(false);
  const hasReceivedFirstAiResponseRef = useRef(false);
  const interviewEndedRef = useRef(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const testMicStreamRef = useRef<MediaStream | null>(null);
  const testMicAudioContextRef = useRef<AudioContext | null>(null);
  const testMicAnalyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  
  // Audio playback queue
  const nextStartTimeRef = useRef<number>(0);
  const ttsChunkCountRef = useRef<number>(0);
  const transcriptLengthRef = useRef<number>(0);
  const noResponseTimerRef = useRef<number | null>(null);
  const userSpeechActiveRef = useRef<boolean>(false);
  const timerIntervalRef = useRef<number | null>(null);

  const clearNoResponseTimer = () => {
    if (noResponseTimerRef.current !== null) {
      window.clearTimeout(noResponseTimerRef.current);
      noResponseTimerRef.current = null;
    }
  };

  const armNoResponseTimer = () => {
    const ws = wsRef.current;
    clearNoResponseTimer();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    noResponseTimerRef.current = window.setTimeout(() => {
      const liveWs = wsRef.current;
      if (!liveWs || liveWs.readyState !== WebSocket.OPEN) return;
      if (isAgentSpeakingRef.current) return;
      if (userSpeechActiveRef.current) return;
      liveWs.send(JSON.stringify({ type: 'no_response_timeout' }));
    }, NO_RESPONSE_REASK_MS);
  };

  useEffect(() => {
    if (token) {
      getInterview(token)
        .then(setInterview)
        .catch(() => setError('面试链接无效或已过期'))
        .finally(() => setLoading(false));
    }
    
    // Enumerate devices
    const getDevices = async () => {
      try {
        // Request permission first to get device labels
        const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const allDevices = await navigator.mediaDevices.enumerateDevices();
        
        // Release the temporary stream immediately
        tempStream.getTracks().forEach(t => t.stop());
        
        setDevices(allDevices);
        
        const defaultMic = allDevices.find(d => d.kind === 'audioinput');
        const defaultSpeaker = allDevices.find(d => d.kind === 'audiooutput');
        
        if (defaultMic) setSelectedMicrophone(defaultMic.deviceId);
        if (defaultSpeaker) setSelectedSpeaker(defaultSpeaker.deviceId);
      } catch (err) {
        console.error('Error enumerating devices:', err);
      }
    };
    getDevices();
  }, [token]);

  const startInterview = async () => {
    if (!token) return;
    
    // 0. Cleanup any ongoing tests
    stopMicTest();
    setIsTestingSpeaker(false);
    
    setShowDeviceSelection(false);
    setStatus('connecting');

    try {
      // 1. Setup Audio Input
      console.log('[MIC] Requesting stream for device:', selectedMicrophone);
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: { 
          deviceId: selectedMicrophone ? { exact: selectedMicrophone } : undefined,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        } 
      });
      streamRef.current = stream;
      console.log('[MIC] Stream acquired:', stream.id, 'active:', stream.active);
      
      // Realtime PCM16 requires 24kHz for both input and output
      const audioContext = new AudioContext({ sampleRate: 24000 });
      audioContextRef.current = audioContext;
      
      // Proactively resume AudioContext on user click
      if (audioContext.state === 'suspended') {
        console.log('[MIC] AudioContext suspended, resuming...');
        await audioContext.resume();
      }
      console.log('[MIC] AudioContext state:', audioContext.state);
      
      nextStartTimeRef.current = audioContext.currentTime;
      console.log('[TTS] AudioContext created, state =', audioContext.state, 'sampleRate =', audioContext.sampleRate);
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(2048, 1, 1);
      processorRef.current = processor;
      
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      silentGainRef.current = silentGain;

      // 2. Setup WebSocket
      const wsUrl = buildRealtimeWsUrl(token);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

        ws.onopen = async () => {
          setStatus('connected');
          setHasReceivedFirstAiResponse(false);
          hasReceivedFirstAiResponseRef.current = false;
          interviewEndedRef.current = false;
          console.log('[TTS] ws.onopen, AudioContext state =', audioContext.state);
        
        // Start interview timer
        setElapsedTime(0);
        timerIntervalRef.current = window.setInterval(() => {
          setElapsedTime(prev => prev + 1);
        }, 1000);

        try {
          if (audioContext.state === 'suspended') {
            console.log('[TTS] AudioContext is suspended on open, calling resume()');
            await audioContext.resume();
            console.log('[TTS] AudioContext state after resume =', audioContext.state);
          }
        } catch (e) {
          console.warn('[TTS] Failed to resume AudioContext:', e);
        }
        source.connect(processor);
        processor.connect(silentGainRef.current!);
        silentGainRef.current!.connect(audioContext.destination);
        
        console.log('[TTS] WebSocket open, audio graph wired. ws.readyState =', ws.readyState);
      };

      ws.onmessage = async (event) => {
        const data = json_parse_safe(event.data);
        if (!data) return;

        console.log('[WS] Event:', data.type, data);

        if (data.type === 'response.audio.delta') {
          if (!data.audio) {
            console.warn('[TTS] response.audio.delta without audio payload:', data);
          } else {
            ttsChunkCountRef.current += 1;
            console.log(
              '[TTS] response.audio.delta chunk #',
              ttsChunkCountRef.current,
              'base64 length =',
              data.audio.length
            );
          }
          enqueueAudio(data.audio);
        } else if (data.type === 'response.audio_transcript.delta') {
          const delta = data.delta || '';
          transcriptLengthRef.current += delta.length;
          console.log(
            '[TTS] response.audio_transcript.delta, deltaLen =',
            delta.length,
            'totalTranscriptLen =',
            transcriptLengthRef.current
          );
          setTranscript(prev => prev + delta);
        } else if (data.type === 'response.created') {
          // Update first response flag
          if (!hasReceivedFirstAiResponseRef.current) {
            hasReceivedFirstAiResponseRef.current = true;
            setHasReceivedFirstAiResponse(true);
            console.log('[TTS] First AI response received, opening mic gate');
          }

          // Preemptively set speaking flag when a new response starts by advancing nextStartTime
          if (audioContextRef.current) {
            // Pre-lock for 1.5 seconds to cover initial processing/first chunk arrival
            nextStartTimeRef.current = Math.max(nextStartTimeRef.current, audioContextRef.current.currentTime + 1.5);
            console.log('[TTS] Pre-locking mic for 1.5s on response.created');
          }

          // Clear transcript for new response
          setTranscript('');
          ttsChunkCountRef.current = 0;
          transcriptLengthRef.current = 0;
          console.log('[TTS] New response.created, reset audio chunk counter');
        } else if (data.type === 'interview.natural_end') {
          console.log('[WS] Interview natural end received');
          interviewEndedRef.current = true;
          // Start 15s countdown
          setCountdown(15);
          const timer = setInterval(() => {
            setCountdown(prev => {
              console.log('[COUNTDOWN] Current:', prev);
              if (prev === null || prev <= 1) {
                clearInterval(timer);
                if (prev === 1) {
                  console.log('[COUNTDOWN] Reached 1, triggering handleFinish');
                  // Trigger automatic finish
                  handleFinish();
                }
                return 0;
              }
              return prev - 1;
            });
          }, 1000);
        } else if (data.type === 'error') {
          console.error('Realtime Error:', data.error);
        }
      };

      ws.onerror = () => {
        console.error('[WS] error');
        setStatus('error');
        cleanupInterview();
      };
      ws.onclose = (evt) => {
        console.log('[WS] closed, code =', evt.code, 'reason =', evt.reason);
        setStatus('idle');
        cleanupInterview();
      };

      let frameCount = 0;
      processor.onaudioprocess = (e) => {
        if (ws.readyState === WebSocket.OPEN && audioContextRef.current) {
          const inputData = e.inputBuffer.getChannelData(0);
          
          // Simple RMS volume check to filter out silence
          let sum = 0;
          for (let i = 0; i < inputData.length; i++) {
            sum += inputData[i] * inputData[i];
          }
          const rms = Math.sqrt(sum / inputData.length);
          setVolume(rms); // Update volume for visualization
          
          const now = audioContextRef.current.currentTime;
          // Strategy A: Time-based gating. 
          // Block if current time is before scheduled audio ends + 0.0s safety buffer
          const isActuallySpeaking = now < (nextStartTimeRef.current + 0.0);
          
          // Update state only on change to avoid re-renders
          if (isActuallySpeaking !== isAgentSpeakingRef.current) {
            const wasSpeaking = isAgentSpeakingRef.current;
            isAgentSpeakingRef.current = isActuallySpeaking;
            setIsAgentSpeaking(isActuallySpeaking);
            
            if (isActuallySpeaking) {
              // AI started speaking
              userSpeechActiveRef.current = false;
              clearNoResponseTimer();
            } else if (wasSpeaking) {
              // AI finished speaking - this is the human-centric start point
              console.log('[TIMER] AI finished speaking, arming no-response timer');
              armNoResponseTimer();
            }
          }

          frameCount += 1;
          if (frameCount % 30 === 0) {
            console.log('[MIC] onaudioprocess rms =', rms, 'frame =', frameCount, 'isAgentSpeaking =', isActuallySpeaking, 'now =', now, 'nextStart =', nextStartTimeRef.current);
          }
          
          // Gate 1: Block audio before the first AI response
          if (!hasReceivedFirstAiResponseRef.current) {
            return;
          }

          // Gate 2: Block audio after the interview has naturally ended
          if (interviewEndedRef.current) {
            return;
          }

          // Gate 3: Strategy A: Time-based gating (Half-duplex)
          // Skip sending audio if the agent is speaking
          if (isActuallySpeaking) {
            return;
          }

          // Frontend-side no-response detection:
          // - user speech start: cancel timer
          // - user speech end: re-arm timer
          const isUserSpeaking = rms > USER_SPEECH_RMS_THRESHOLD;
          if (isUserSpeaking !== userSpeechActiveRef.current) {
            userSpeechActiveRef.current = isUserSpeaking;
            if (isUserSpeaking) {
              clearNoResponseTimer();
            } else {
              armNoResponseTimer();
            }
          }

          const pcm16 = floatTo16BitPCM(inputData);
          const base64Audio = arrayBufferToBase64(pcm16);
          ws.send(JSON.stringify({ type: 'audio', audio: base64Audio }));
        }
      };

    } catch (err) {
      console.error('Failed to start interview:', err);
      setStatus('error');
    }
  };

  const testMicrophone = async () => {
    if (isTestingMic) {
      stopMicTest();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: selectedMicrophone ? { exact: selectedMicrophone } : undefined,
        },
      });
      testMicStreamRef.current = stream;

      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      testMicAudioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      testMicAnalyserRef.current = analyser;

      setIsTestingMic(true);
      
      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateVolume = () => {
        if (!testMicAnalyserRef.current) return;
        testMicAnalyserRef.current.getByteTimeDomainData(dataArray);
        
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          const v = (dataArray[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / bufferLength);
        setTestMicVolume(rms);
        animationFrameRef.current = requestAnimationFrame(updateVolume);
      };
      updateVolume();

      // Auto stop after 10 seconds
      setTimeout(() => {
        stopMicTest();
      }, 10000);

    } catch (err) {
      console.error('Microphone test failed:', err);
      alert('无法访问麦克风，请检查浏览器权限和设备选择。');
    }
  };

  const stopMicTest = () => {
    setIsTestingMic(false);
    setTestMicVolume(0);
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (testMicStreamRef.current) {
      testMicStreamRef.current.getTracks().forEach(t => t.stop());
      testMicStreamRef.current = null;
    }
    if (testMicAudioContextRef.current) {
      testMicAudioContextRef.current.close().catch(e => console.warn('Error closing test AudioContext:', e));
      testMicAudioContextRef.current = null;
    }
    testMicAnalyserRef.current = null;
  };

  const testSpeaker = async () => {
    if (isTestingSpeaker) return;

    try {
      setIsTestingSpeaker(true);
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const oscillator = ctx.createOscillator();
      const gainNode = ctx.createGain();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;

      oscillator.type = 'sine';
      oscillator.frequency.value = 440; // A4
      gainNode.gain.setValueAtTime(0, ctx.currentTime);
      gainNode.gain.linearRampToValueAtTime(0.2, ctx.currentTime + 0.1);
      gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + 2);

      oscillator.connect(gainNode);
      gainNode.connect(analyser);
      analyser.connect(ctx.destination);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateVolume = () => {
        analyser.getByteTimeDomainData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          const v = (dataArray[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / bufferLength);
        setTestSpeakerVolume(rms);
        
        if (ctx.state !== 'closed') {
          animationFrameRef.current = requestAnimationFrame(updateVolume);
        }
      };
      updateVolume();

      oscillator.start();
      oscillator.stop(ctx.currentTime + 2);

      setTimeout(() => {
        setIsTestingSpeaker(false);
        setTestSpeakerVolume(0);
        if (animationFrameRef.current) {
          cancelAnimationFrame(animationFrameRef.current);
        }
        ctx.close();
      }, 2100);

    } catch (err) {
      console.error('Speaker test failed:', err);
      alert('无法播放测试音，请检查浏览器音频输出设置。');
      setIsTestingSpeaker(false);
    }
  };

  const json_parse_safe = (str: string) => {
    try { return JSON.parse(str); } catch { return null; }
  };

  const floatTo16BitPCM = (input: Float32Array) => {
    const buffer = new ArrayBuffer(input.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buffer;
  };

  const arrayBufferToBase64 = (buffer: ArrayBuffer) => {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  };

  const enqueueAudio = (base64Audio: string) => {
    if (!audioContextRef.current) {
      console.warn('[TTS] enqueueAudio called but audioContextRef is null');
      return;
    }
    if (!base64Audio) {
      console.warn('[TTS] enqueueAudio called with empty base64Audio');
      return;
    }
    
    let binary: string;
    try {
      binary = atob(base64Audio);
    } catch (e) {
      console.error('[TTS] Failed to decode base64 audio:', e, 'len =', base64Audio.length);
      return;
    }
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    
    // Convert PCM16 to Float32
    if (bytes.byteLength % 2 !== 0) {
      console.warn('[TTS] PCM16 byteLength is not even, len =', bytes.byteLength);
    }

    const pcm16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768;
    }
    
    console.log(
      '[TTS] Decoded audio chunk: samples =',
      float32.length,
      'firstSample =',
      float32[0]
    );

    // Realtime PCM16 is always 24kHz
    const audioBuffer = audioContextRef.current.createBuffer(1, float32.length, 24000);
    audioBuffer.getChannelData(0).set(float32);
    
    const source = audioContextRef.current.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContextRef.current.destination);
    
    const startTime = Math.max(audioContextRef.current.currentTime, nextStartTimeRef.current);
    console.log(
      '[TTS] Scheduling audio playback at',
      startTime,
      'currentTime =',
      audioContextRef.current.currentTime,
      'duration =',
      audioBuffer.duration
    );
    try {
      source.start(startTime);
    } catch (e) {
      console.error('[TTS] Failed to start audio source:', e);
      return;
    }
    nextStartTimeRef.current = startTime + audioBuffer.duration;
  };

  const handleFinish = async () => {
    if (!token || isFinishing) return;
    
    console.log('[FINISH] Starting finish process for token:', token);
    setIsFinishing(true);
    cleanupInterview();

    try {
      console.log('[FINISH] Calling completeInterview API...');
      await completeInterview(token);
      console.log('[FINISH] API call successful, navigating to done page...');
      navigate(`/interview/${token}/done`);
    } catch (err) {
      console.error('[FINISH] Failed to complete interview:', err);
      setError('完成面试失败，请重试');
      setIsFinishing(false);
    }
  };

  const cleanupInterview = () => {
    clearNoResponseTimer();
    if (timerIntervalRef.current) {
      window.clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    userSpeechActiveRef.current = false;

    // 1. Close WebSocket
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    // 2. Stop Media Tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }

    // 3. Cleanup Audio Graph
    if (processorRef.current) {
      processorRef.current.onaudioprocess = null;
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (silentGainRef.current) {
      silentGainRef.current.disconnect();
      silentGainRef.current = null;
    }

    // 4. Close AudioContext
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(e => console.warn('Error closing AudioContext:', e));
      audioContextRef.current = null;
    }

    isAgentSpeakingRef.current = false;
    setIsAgentSpeaking(false);

    // 6. Reset states
    setVolume(0);
    setStatus('idle');
  };

  useEffect(() => {
    return () => {
      cleanupInterview();
      stopMicTest();
    };
  }, []);

  if (loading) return <div style={{ textAlign: 'center', marginTop: '50px' }}>加载中...</div>;
  if (error) return <div style={{ textAlign: 'center', marginTop: '50px', color: 'red' }}>{error}</div>;

  const microphones = devices.filter(d => d.kind === 'audioinput');
  const speakers = devices.filter(d => d.kind === 'audiooutput');

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '40px auto', textAlign: 'center' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h1 style={{ margin: 0 }}>AI 实时语音面试</h1>
        {status === 'connected' && (
          <div style={{ 
            padding: '5px 15px', 
            backgroundColor: '#e9ecef', 
            borderRadius: '20px', 
            fontWeight: 'bold',
            color: '#495057',
            fontSize: '1.1rem'
          }}>
            ⏱️ {formatTime(elapsedTime)}
          </div>
        )}
      </div>
      <p>岗位: {interview?.position}</p>
      
      {showDeviceSelection ? (
        <div style={{ 
          padding: '30px', 
          backgroundColor: '#fff', 
          borderRadius: '12px', 
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
          textAlign: 'left',
          marginBottom: '30px'
        }}>
          <h3>设备测试与选择</h3>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px' }}>选择麦克风:</label>
            <select 
              value={selectedMicrophone} 
              onChange={(e) => setSelectedMicrophone(e.target.value)}
              style={{ width: '100%', padding: '10px', borderRadius: '6px', border: '1px solid #ccc' }}
            >
              {microphones.map(d => (
                <option key={d.deviceId} value={d.deviceId}>{d.label || `麦克风 ${d.deviceId.slice(0, 5)}`}</option>
              ))}
            </select>
            <div style={{ display: 'flex', alignItems: 'center', marginTop: '10px' }}>
              <button
                type="button"
                onClick={testMicrophone}
                style={{
                  padding: '6px 12px',
                  fontSize: '0.9rem',
                  backgroundColor: isTestingMic ? '#dc3545' : '#f0f0f0',
                  color: isTestingMic ? 'white' : 'black',
                  borderRadius: '6px',
                  border: '1px solid #ccc',
                  cursor: 'pointer',
                }}
              >
                {isTestingMic ? '停止测试' : '测试麦克风'}
              </button>
              <VolumeBar level={testMicVolume} isActive={isTestingMic} />
            </div>
          </div>
          
          <div style={{ marginBottom: '30px' }}>
            <label style={{ display: 'block', marginBottom: '8px' }}>选择扬声器:</label>
            <select 
              value={selectedSpeaker} 
              onChange={(e) => setSelectedSpeaker(e.target.value)}
              style={{ width: '100%', padding: '10px', borderRadius: '6px', border: '1px solid #ccc' }}
            >
              {speakers.map(d => (
                <option key={d.deviceId} value={d.deviceId}>{d.label || `扬声器 ${d.deviceId.slice(0, 5)}`}</option>
              ))}
            </select>
            <p style={{ fontSize: '0.85rem', color: '#666', marginTop: '8px' }}>
              注：部分浏览器可能不支持直接切换扬声器，将使用系统默认输出。
            </p>
            <div style={{ display: 'flex', alignItems: 'center', marginTop: '10px' }}>
              <button
                type="button"
                onClick={testSpeaker}
                style={{
                  padding: '6px 12px',
                  fontSize: '0.9rem',
                  backgroundColor: isTestingSpeaker ? '#28a745' : '#f0f0f0',
                  color: isTestingSpeaker ? 'white' : 'black',
                  borderRadius: '6px',
                  border: '1px solid #ccc',
                  cursor: 'pointer',
                }}
              >
                {isTestingSpeaker ? '正在播放...' : '测试扬声器'}
              </button>
              <VolumeBar level={testSpeakerVolume} isActive={isTestingSpeaker} />
            </div>
          </div>

          <button 
            onClick={startInterview}
            style={{ 
              width: '100%', 
              padding: '15px', 
              fontSize: '1.1rem', 
              backgroundColor: '#007bff', 
              color: 'white', 
              border: 'none', 
              borderRadius: '8px', 
              cursor: 'pointer' 
            }}
          >
            确认设备并开始面试
          </button>
        </div>
      ) : (
        <div style={{ 
          height: '300px', 
          backgroundColor: '#f5f5f5', 
          borderRadius: '12px', 
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          marginBottom: '30px',
          border: '2px solid #eee',
          position: 'relative'
        }}>
          {status === 'connecting' && <p>正在连接 AI 面试官...</p>}
          {status === 'connected' && (
            <div>
              <div style={{ fontSize: '3rem', marginBottom: '20px' }}>🎙️</div>
              
              {/* Volume Indicator */}
              <div style={{ 
                width: '100px', 
                height: '10px', 
                backgroundColor: '#ddd', 
                margin: '0 auto 20px', 
                borderRadius: '5px',
                overflow: 'hidden'
              }}>
                <div style={{ 
                  width: `${Math.min(100, volume * 500)}%`, 
                  height: '100%', 
                  backgroundColor: volume > 0.03 ? '#28a745' : '#ffc107',
                  transition: 'width 0.1s'
                }} />
              </div>

              <p>正在通话中...</p>
              {!hasReceivedFirstAiResponse && (
                <p style={{ color: '#6c757d', fontSize: '0.9rem', fontWeight: 'bold' }}>
                  请等待 AI 面试官开场...
                </p>
              )}
              {isAgentSpeaking && (
                <p style={{ color: '#007bff', fontSize: '0.9rem', fontWeight: 'bold' }}>
                  AI 正在发言，请稍后再回答...
                </p>
              )}
              {countdown !== null && (
                <div style={{ 
                  marginTop: '10px', 
                  padding: '10px', 
                  backgroundColor: '#fff3cd', 
                  color: '#856404', 
                  borderRadius: '8px',
                  border: '1px solid #ffeeba'
                }}>
                  <p style={{ margin: 0, fontWeight: 'bold' }}>面试已结束</p>
                  <p style={{ margin: '5px 0 0', fontSize: '0.9rem' }}>
                    您可以手动点击下方按钮结束，或等待 {countdown} 秒后自动提交。
                  </p>
                </div>
              )}
              <div style={{ marginTop: '20px', fontStyle: 'italic', color: '#666', maxHeight: '100px', overflowY: 'auto' }}>
                {transcript || "等待 AI 发言..."}
              </div>
            </div>
          )}
          {status === 'error' && <p style={{ color: 'red' }}>连接失败，请刷新重试</p>}
        </div>
      )}

      {status === 'connected' && (
        <button 
          onClick={handleFinish}
          style={{ padding: '10px 20px', backgroundColor: '#dc3545', color: 'white', border: 'none', borderRadius: '5px', cursor: 'pointer' }}
        >
          结束面试并生成评分
        </button>
      )}
    </div>
  );
};

export default InterviewPage;
