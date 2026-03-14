import axios from 'axios';
import type { Interview, AnswerResponse } from '../types';

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api';
const RAW_API_BASE_URL = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;

export const API_BASE_URL = RAW_API_BASE_URL.replace(/\/+$/, '');

export const getApiOrigin = (): string => {
  return API_BASE_URL.replace(/\/api$/, '');
};

export const buildRealtimeWsUrl = (token: string): string => {
  const origin = getApiOrigin();
  const wsOrigin = origin.startsWith('https://')
    ? origin.replace(/^https:\/\//, 'wss://')
    : origin.replace(/^http:\/\//, 'ws://');
  return `${wsOrigin}/api/realtime/ws/${token}`;
};

const api = axios.create({
  baseURL: API_BASE_URL,
});

export const getInterview = async (token: string): Promise<Interview> => {
  const response = await api.get(`/interviews/${token}`);
  return response.data;
};

export const submitAnswer = async (
  token: string,
  questionIndex: number,
  audioFile: Blob
): Promise<AnswerResponse> => {
  const formData = new FormData();
  formData.append('question_index', questionIndex.toString());
  formData.append('audio_file', audioFile, `answer_${questionIndex}.webm`);

  const response = await api.post(`/interviews/${token}/answer`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const completeInterview = async (token: string): Promise<any> => {
  const response = await api.post(`/interviews/${token}/complete`);
  return response.data;
};

export const createInterview = async (data?: { 
  name?: string; 
  position?: string; 
  position_key?: string;
  resume_brief?: string 
}): Promise<Interview> => {
  const response = await api.post('/interviews/create', data ?? {});
  return response.data;
};

export const uploadJobProfile = async (data: {
  position_key: string;
  position_name?: string;
  jd_file: File;
  question_csv: File;
}): Promise<any> => {
  const formData = new FormData();
  formData.append('position_key', data.position_key);
  if (data.position_name) formData.append('position_name', data.position_name);
  formData.append('jd_file', data.jd_file);
  formData.append('question_csv', data.question_csv);

  const response = await api.post('/job_profiles/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const getJobProfiles = async (): Promise<any[]> => {
  const response = await api.get('/job_profiles/');
  return response.data;
};

export default api;
