import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';

const AdminInterviewDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    axios.get(`http://localhost:8000/api/admin/interviews/${id}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    .then(res => setData(res.data))
    .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div style={{ padding: '20px', color: 'var(--text)' }}>加载中...</div>;
  if (!data) return <div style={{ padding: '20px', color: 'var(--text)' }}>未找到面试详情</div>;

  const { interview, answers } = data;

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto', color: 'var(--text)' }}>
      <button 
        onClick={() => navigate('/admin/interviews')}
        style={{ 
          marginBottom: '20px', 
          padding: '8px 16px', 
          cursor: 'pointer',
          backgroundColor: 'var(--surface)',
          color: 'var(--text)',
          border: '1px solid var(--border)',
          borderRadius: '4px'
        }}
      >
        ← 返回列表
      </button>
      <h2 style={{ color: 'var(--text)' }}>面试详情: {interview.name} - {interview.position}</h2>
      
      <div style={{ marginBottom: '30px', padding: '20px', backgroundColor: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
        <h3 style={{ color: 'var(--text)', marginTop: 0 }}>AI 评分结果</h3>
        {interview.evaluation_result ? (
          <div>
            <p><strong>总分:</strong> {interview.evaluation_result.total_score}</p>
            <p><strong>评语:</strong> {interview.evaluation_result.comment}</p>
            <h4 style={{ color: 'var(--text)' }}>维度分:</h4>
            <ul>
              {Object.entries(interview.evaluation_result.dimension_scores).map(([k, v]: any) => (
                <li key={k}>{k}: {v}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)' }}>暂无评分（面试可能尚未完成或正在评估中）</p>
        )}
      </div>

      <h3 style={{ color: 'var(--text)' }}>问答记录</h3>
      {interview.question_set.map((q: any, idx: number) => {
        const answer = answers.find((a: any) => a.question_index === idx);
        return (
          <div key={idx} style={{ marginBottom: '20px', borderLeft: '4px solid var(--primary)', paddingLeft: '15px' }}>
            <p><strong>Q{idx + 1}: {q.question_text}</strong></p>
            <p><strong>回答:</strong> {answer?.transcript || '未回答'}</p>
            {answer?.audio_url && (
              <p><small style={{ color: 'var(--text-muted)' }}>音频文件: {answer.audio_url}</small></p>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default AdminInterviewDetail;
