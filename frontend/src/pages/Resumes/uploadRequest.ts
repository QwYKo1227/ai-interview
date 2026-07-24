export const buildAuthenticatedResumeUpload = (
  positionId: string,
  files: Blob[],
) => {
  const formData = new FormData();
  formData.append('position_id', positionId);
  files.forEach((file) => formData.append('files', file));

  return {
    url: '/resumes/batch',
    formData,
  };
};
