export const MAX_RESUME_FILE_SIZE_MB = 10;
export const MAX_RESUME_FILE_SIZE_BYTES =
  MAX_RESUME_FILE_SIZE_MB * 1024 * 1024;

type ResumeFileCandidate = {
  name: string;
  size: number;
  type?: string;
};

export const getResumeFileValidationError = (
  file: ResumeFileCandidate,
): string | null => {
  const isPdf =
    file.type === 'application/pdf' ||
    file.name.toLowerCase().endsWith('.pdf');

  if (!isPdf) {
    return '只允许上传 PDF 格式的文件';
  }
  if (file.size > MAX_RESUME_FILE_SIZE_BYTES) {
    return `单个简历文件不能超过 ${MAX_RESUME_FILE_SIZE_MB} MB`;
  }
  return null;
};

export const buildAuthenticatedResumeUpload = (
  positionId: string,
  files: Blob[],
) => {
  const oversizedFile = files.find(
    (file) => file.size > MAX_RESUME_FILE_SIZE_BYTES,
  );
  if (oversizedFile) {
    throw new Error(
      `单个简历文件不能超过 ${MAX_RESUME_FILE_SIZE_MB} MB`,
    );
  }

  const formData = new FormData();
  formData.append('position_id', positionId);
  files.forEach((file) => formData.append('files', file));

  return {
    url: '/resumes/batch',
    formData,
  };
};
