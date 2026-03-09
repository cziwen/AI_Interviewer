export interface Question {
  order_index: number;
  question_text: string;
}

export interface Interview {
  id: number;
  name: string | null;
  position: string | null;
  status: string;
  link_token: string;
  question_set: Question[];
  created_at: string;
}

export interface AnswerResponse {
  id: number;
  question_index: number;
  audio_url: string;
  transcript: string | null;
  created_at: string;
}

export interface EvaluationResult {
  total_score: number;
  dimension_scores: Record<string, number>;
  comment: string;
}
