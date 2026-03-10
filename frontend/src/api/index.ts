import axios from 'axios';
import type { Interview, AnswerResponse } from '../types';

const API_BASE_URL = 'http://localhost:8000/api';

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

export const createInterview = async (data?: { name?: string; position?: string; resume_brief?: string }): Promise<Interview> => {
  const response = await api.post('/interviews/create', data ?? {});
  return response.data;
};

export default api;
