import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getInterview, completeInterview } from '../api';
import type { Interview } from '../types';

const InterviewPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [transcript, setTranscript] = useState<string>('');
  
  // Device selection states
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicrophone, setSelectedMicrophone] = useState<string>('');
  const [selectedSpeaker, setSelectedSpeaker] = useState<string>('');
  const [showDeviceSelection, setShowDeviceSelection] = useState(true);
  
  // Volume visualization
  const [volume, setVolume] = useState<number>(0);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  
  // Audio playback queue
  const nextStartTimeRef = useRef<number>(0);

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
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const allDevices = await navigator.mediaDevices.enumerateDevices();
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
    setShowDeviceSelection(false);
    setStatus('connecting');

    try {
      // 1. Setup Audio Input
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: { deviceId: selectedMicrophone ? { exact: selectedMicrophone } : undefined } 
      });
      streamRef.current = stream;
      
      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;
      nextStartTimeRef.current = audioContext.currentTime;
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      // 2. Setup WebSocket
      const wsUrl = `ws://localhost:8000/api/realtime/ws/${token}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus('connected');
        source.connect(processor);
        processor.connect(audioContext.destination);
      };

      ws.onmessage = async (event) => {
        const data = json_parse_safe(event.data);
        if (!data) return;

        if (data.type === 'response.audio.delta') {
          enqueueAudio(data.audio);
        } else if (data.type === 'response.audio_transcript.delta') {
          setTranscript(prev => prev + data.delta);
        }
      };

      ws.onerror = () => setStatus('error');
      ws.onclose = () => setStatus('idle');

      processor.onaudioprocess = (e) => {
        if (ws.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          
          // Simple RMS volume check to filter out silence
          let sum = 0;
          for (let i = 0; i < inputData.length; i++) {
            sum += inputData[i] * inputData[i];
          }
          const rms = Math.sqrt(sum / inputData.length);
          setVolume(rms); // Update volume for visualization
          
          // Increased threshold from 0.01 to 0.03 to filter environment noise better
          if (rms > 0.03) {
            const pcm16 = floatTo16BitPCM(inputData);
            const base64Audio = arrayBufferToBase64(pcm16);
            ws.send(JSON.stringify({ type: 'audio', audio: base64Audio }));
          }
        }
      };

    } catch (err) {
      console.error('Failed to start interview:', err);
      setStatus('error');
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
    if (!audioContextRef.current) return;
    
    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    
    // Convert PCM16 to Float32
    const pcm16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768;
    }
    
    const audioBuffer = audioContextRef.current.createBuffer(1, float32.length, 16000);
    audioBuffer.getChannelData(0).set(float32);
    
    const source = audioContextRef.current.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContextRef.current.destination);
    
    const startTime = Math.max(audioContextRef.current.currentTime, nextStartTimeRef.current);
    source.start(startTime);
    nextStartTimeRef.current = startTime + audioBuffer.duration;
  };

  const handleFinish = async () => {
    if (!token) return;
    
    // Cleanup
    wsRef.current?.close();
    streamRef.current?.getTracks().forEach(t => t.stop());
    audioContextRef.current?.close();

    try {
      await completeInterview(token);
      navigate(`/interview/${token}/done`);
    } catch (err) {
      setError('完成面试失败，请重试');
    }
  };

  if (loading) return <div style={{ textAlign: 'center', marginTop: '50px' }}>加载中...</div>;
  if (error) return <div style={{ textAlign: 'center', marginTop: '50px', color: 'red' }}>{error}</div>;

  const microphones = devices.filter(d => d.kind === 'audioinput');
  const speakers = devices.filter(d => d.kind === 'audiooutput');

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '40px auto', textAlign: 'center' }}>
      <h1>AI 实时语音面试</h1>
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
