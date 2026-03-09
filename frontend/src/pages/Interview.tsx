import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getInterview, submitAnswer, completeInterview } from '../api';
import type { Interview } from '../types';
import AudioRecorder from '../components/AudioRecorder';

const InterviewPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [isRecording, setIsRecording] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    if (token) {
      getInterview(token)
        .then(setInterview)
        .catch(() => setError('面试链接无效或已过期'))
        .finally(() => setLoading(false));
    }
  }, [token]);

  const handleAudioStop = (blob: Blob) => {
    setRecordedBlob(blob);
  };

  const handleNext = async () => {
    if (!interview || !token) return;
    
    if (!recordedBlob) {
      alert('请先录制回答');
      return;
    }

    setIsUploading(true);
    try {
      await submitAnswer(token, currentQuestionIndex, recordedBlob);
      setRecordedBlob(null); // Reset for next question
      
      if (currentQuestionIndex < interview.question_set.length - 1) {
        setCurrentQuestionIndex(currentQuestionIndex + 1);
      } else {
        await completeInterview(token);
        navigate(`/interview/${token}/done`);
      }
    } catch (err) {
      setError('提交回答失败，请重试');
    } finally {
      setIsUploading(false);
    }
  };

  if (loading) return <div style={{ textAlign: 'center', marginTop: '50px', color: 'var(--text)' }}>加载中...</div>;
  if (error) return <div style={{ textAlign: 'center', marginTop: '50px', color: 'var(--error)' }}>{error}</div>;
  if (!interview) return <div style={{ textAlign: 'center', marginTop: '50px', color: 'var(--text)' }}>未找到面试信息</div>;

  const currentQuestion = interview.question_set[currentQuestionIndex];

  return (
    <div style={{ padding: '20px', maxWidth: '600px', margin: '40px auto', fontFamily: 'sans-serif', color: 'var(--text)' }}>
      <header style={{ marginBottom: '30px', textAlign: 'center' }}>
        <h1 style={{ color: 'var(--text)' }}>AI 面试: {interview.position || '基础面试'}</h1>
        <p style={{ color: 'var(--text-muted)' }}>候选人: {interview.name || '各位'}</p>
      </header>

      <div style={{ 
        marginBottom: '30px', 
        padding: '30px', 
        backgroundColor: 'var(--surface)', 
        borderRadius: '12px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
        border: '1px solid var(--border)'
      }}>
        <div style={{ color: 'var(--primary)', fontWeight: 'bold', marginBottom: '10px' }}>
          问题 {currentQuestionIndex + 1} / {interview.question_set.length}
        </div>
        <p style={{ fontSize: '1.4rem', lineHeight: '1.6', margin: 0, color: 'var(--text)' }}>
          {currentQuestion.question_text}
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <AudioRecorder 
          onStop={handleAudioStop} 
          isRecording={isRecording} 
          setIsRecording={setIsRecording} 
        />
        
        {recordedBlob && !isRecording && (
          <div style={{ marginTop: '10px', color: 'var(--success)' }}>
            ✓ 已录制 ({(recordedBlob.size / 1024).toFixed(1)} KB)
          </div>
        )}

        <div style={{ marginTop: '40px', width: '100%' }}>
          <button 
            onClick={handleNext}
            disabled={isRecording || isUploading || (!recordedBlob && !isRecording)}
            style={{ 
              width: '100%',
              padding: '15px', 
              fontSize: '1.1rem',
              backgroundColor: 'var(--primary)',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: (isRecording || isUploading || !recordedBlob) ? 'not-allowed' : 'pointer',
              opacity: (isRecording || isUploading || !recordedBlob) ? 0.6 : 1,
              transition: 'all 0.3s'
            }}
          >
            {isUploading ? '正在提交...' : (currentQuestionIndex < interview.question_set.length - 1 ? '下一题' : '完成面试')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default InterviewPage;
