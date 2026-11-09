# AI Interview API 接口索引

外部业务接口的完整参数、权限、响应与数据模型见 [离线接口手册](external-api/index.html#reference)。接入步骤见 [API 接入文档](api-calling-guide.md)。

本索引的路径均已包含 `/api`；请拼接服务地址 `https://interview.careray.com`。公司级数据仍受账号角色和资源分配权限限制。平台管理、运维及已停用接口不在此交付范围。

## 账号与认证

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/auth/tenants` | [查询可登录公司](external-api/index.html#list_login_tenants_api_auth_tenants_get) | 无需账号 Token |
| POST | `/api/auth/login` | [账号登录](external-api/index.html#login_api_auth_login_post) | 无需账号 Token |
| GET | `/api/auth/me` | [查询当前用户](external-api/index.html#read_users_me_api_auth_me_get) | 公司 Token |
| PUT | `/api/auth/me` | [更新当前用户资料](external-api/index.html#update_users_me_api_auth_me_put) | 公司 Token |
| POST | `/api/auth/change-password` | [修改当前用户密码](external-api/index.html#change_password_api_auth_change_password_post) | 公司 Token |
| GET | `/api/auth/users` | [查询公司用户](external-api/index.html#get_users_api_auth_users_get) | 公司 Token |
| POST | `/api/auth/users` | [创建公司用户](external-api/index.html#create_user_api_auth_users_post) | 公司 Token |
| GET | `/api/auth/interviewers` | [查询面试官](external-api/index.html#get_interviewers_api_auth_interviewers_get) | 公司 Token |
| PUT | `/api/auth/users/{user_id}` | [更新用户资料](external-api/index.html#update_user_api_auth_users__user_id__put) | 公司 Token |
| DELETE | `/api/auth/users/{user_id}` | [删除用户](external-api/index.html#delete_user_api_auth_users__user_id__delete) | 公司 Token |
| PUT | `/api/auth/users/{user_id}/role` | [修改用户角色](external-api/index.html#update_user_role_api_auth_users__user_id__role_put) | 公司 Token |
| PUT | `/api/auth/users/{user_id}/status` | [启用或禁用用户](external-api/index.html#toggle_user_status_api_auth_users__user_id__status_put) | 公司 Token |
| PUT | `/api/auth/users/{user_id}/password` | [重置用户密码](external-api/index.html#reset_user_password_api_auth_users__user_id__password_put) | 公司 Token |

## 岗位管理

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| POST | `/api/positions` | [创建岗位](external-api/index.html#create_position_route_api_positions_post) | 公司 Token |
| GET | `/api/positions` | [查询岗位列表](external-api/index.html#get_positions_route_api_positions_get) | 公司 Token |
| GET | `/api/positions/hiring-managers` | [查询岗位负责人选项](external-api/index.html#get_hiring_managers_route_api_positions_hiring_managers_get) | 公司 Token |
| GET | `/api/positions/departments` | [查询部门选项](external-api/index.html#get_position_departments_route_api_positions_departments_get) | 公司 Token |
| GET | `/api/positions/public` | [查询公开岗位](external-api/index.html#get_public_positions_route_api_positions_public_get) | 无需账号 Token |
| POST | `/api/positions/generate-jd` | [生成岗位描述](external-api/index.html#generate_jd_route_api_positions_generate_jd_post) | 公司 Token |
| POST | `/api/positions/generate-jd-stream` | [流式生成岗位描述](external-api/index.html#generate_jd_stream_route_api_positions_generate_jd_stream_post) | 公司 Token |
| POST | `/api/positions/chat-jd-stream` | [对话修改岗位描述](external-api/index.html#chat_jd_stream_route_api_positions_chat_jd_stream_post) | 公司 Token |
| POST | `/api/positions/batch-status` | [批量修改岗位状态](external-api/index.html#batch_update_position_status_route_api_positions_batch_status_post) | 公司 Token |
| GET | `/api/positions/{position_id}` | [查询岗位详情](external-api/index.html#get_position_route_api_positions__position_id__get) | 公司 Token |
| PUT | `/api/positions/{position_id}` | [更新岗位](external-api/index.html#update_position_route_api_positions__position_id__put) | 公司 Token |
| DELETE | `/api/positions/{position_id}` | [删除岗位](external-api/index.html#delete_position_route_api_positions__position_id__delete) | 公司 Token |
| GET | `/api/positions/{position_id}/stats` | [查询岗位统计](external-api/index.html#get_position_stats_route_api_positions__position_id__stats_get) | 公司 Token |
| GET | `/api/positions/{position_id}/question-banks` | [查询岗位关联题库](external-api/index.html#get_position_question_banks_route_api_positions__position_id__question_banks_get) | 公司 Token |
| POST | `/api/positions/{position_id}/restore` | [恢复岗位](external-api/index.html#restore_position_route_api_positions__position_id__restore_post) | 公司 Token |

## 公开岗位

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/public/positions` | [查询域名对应公司的公开岗位](external-api/index.html#get_domain_public_positions_api_public_positions_get) | 无需账号 Token |
| GET | `/api/public/positions/{position_id}` | [查询域名对应公司的公开岗位详情](external-api/index.html#get_domain_public_position_api_public_positions__position_id__get) | 无需账号 Token |
| GET | `/api/public/{tenant_code}/positions` | [查询指定公司的公开岗位](external-api/index.html#get_tenant_public_positions_api_public__tenant_code__positions_get) | 无需账号 Token |
| GET | `/api/public/{tenant_code}/positions/{position_id}` | [查询指定公司的公开岗位详情](external-api/index.html#get_tenant_public_position_api_public__tenant_code__positions__position_id__get) | 无需账号 Token |

## 题库管理

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| POST | `/api/question-banks` | [上传并创建题库](external-api/index.html#create_question_bank_route_api_question_banks_post) | 公司 Token |
| GET | `/api/question-banks` | [查询题库列表](external-api/index.html#get_question_banks_route_api_question_banks_get) | 公司 Token |
| GET | `/api/question-banks/{question_bank_id}` | [查询题库详情](external-api/index.html#get_question_bank_route_api_question_banks__question_bank_id__get) | 公司 Token |
| PUT | `/api/question-banks/{question_bank_id}` | [更新题库](external-api/index.html#update_question_bank_route_api_question_banks__question_bank_id__put) | 公司 Token |
| DELETE | `/api/question-banks/{question_bank_id}` | [删除题库](external-api/index.html#delete_question_bank_route_api_question_banks__question_bank_id__delete) | 公司 Token |

## 简历与部门评审

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/resumes` | [查询简历列表](external-api/index.html#get_resumes_route_api_resumes_get) | 公司 Token |
| POST | `/api/resumes` | [公开投递简历](external-api/index.html#create_resume_route_api_resumes_post) | 无需账号 Token |
| POST | `/api/resumes/check-duplicate` | [检查简历重复](external-api/index.html#check_duplicate_route_api_resumes_check_duplicate_post) | 公司 Token |
| POST | `/api/resumes/batch` | [后台批量上传简历](external-api/index.html#batch_upload_resumes_route_api_resumes_batch_post) | 公司 Token |
| GET | `/api/resumes/my-reviews` | [查询分配给我的部门评审](external-api/index.html#get_my_reviews_route_api_resumes_my_reviews_get) | 公司 Token |
| GET | `/api/resumes/my-pending-review-count` | [查询待部门评审数量](external-api/index.html#get_my_pending_review_count_route_api_resumes_my_pending_review_count_get) | 公司 Token |
| GET | `/api/resumes/pending-hr-decision-count` | [查询待 HR 决策数量](external-api/index.html#get_pending_hr_decision_count_route_api_resumes_pending_hr_decision_count_get) | 公司 Token |
| GET | `/api/resumes/{resume_id}/duplicates` | [查询重复简历](external-api/index.html#get_duplicate_resumes_route_api_resumes__resume_id__duplicates_get) | 公司 Token |
| GET | `/api/resumes/{resume_id}` | [查询简历详情](external-api/index.html#get_resume_route_api_resumes__resume_id__get) | 公司 Token |
| PUT | `/api/resumes/{resume_id}` | [更新简历](external-api/index.html#update_resume_route_api_resumes__resume_id__put) | 公司 Token |
| DELETE | `/api/resumes/{resume_id}` | [删除简历](external-api/index.html#delete_resume_route_api_resumes__resume_id__delete) | 公司 Token |
| POST | `/api/resumes/{resume_id}/reparse` | [重新解析简历](external-api/index.html#reparse_resume_route_api_resumes__resume_id__reparse_post) | 公司 Token |
| GET | `/api/resumes/{resume_id}/department-reviews` | [查询部门评审](external-api/index.html#get_department_reviews_route_api_resumes__resume_id__department_reviews_get) | 公司 Token |
| POST | `/api/resumes/{resume_id}/department-reviews` | [指派部门评审人](external-api/index.html#create_department_review_route_api_resumes__resume_id__department_reviews_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/department-reviews/{review_id}/email-preview` | [预览部门评审邮件](external-api/index.html#preview_department_review_email_api_resumes__resume_id__department_reviews__review_id__email_preview_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/department-reviews/{review_id}/reminder-email-preview` | [预览部门评审提醒邮件](external-api/index.html#preview_department_review_reminder_email_api_resumes__resume_id__department_reviews__review_id__reminder_email_preview_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/department-reviews/{review_id}/send-email` | [发送部门评审邮件](external-api/index.html#send_department_review_email_api_resumes__resume_id__department_reviews__review_id__send_email_post) | 公司 Token |
| PUT | `/api/resumes/{resume_id}/department-reviews/{review_id}` | [提交部门评审](external-api/index.html#complete_department_review_route_api_resumes__resume_id__department_reviews__review_id__put) | 公司 Token |
| DELETE | `/api/resumes/{resume_id}/department-reviews/{review_id}` | [删除部门评审人](external-api/index.html#delete_department_reviewer_route_api_resumes__resume_id__department_reviews__review_id__delete) | 公司 Token |
| PUT | `/api/resumes/{resume_id}/department-reviews/{review_id}/reviewer` | [更换部门评审人](external-api/index.html#reassign_department_reviewer_route_api_resumes__resume_id__department_reviews__review_id__reviewer_put) | 公司 Token |
| POST | `/api/resumes/{resume_id}/department-reviews/{review_id}/review-link` | [重新生成部门评审链接](external-api/index.html#reissue_department_review_link_route_api_resumes__resume_id__department_reviews__review_id__review_link_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/hr-decision` | [提交 HR 决策](external-api/index.html#submit_hr_decision_route_api_resumes__resume_id__hr_decision_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/confirm-rejection` | [确认淘汰](external-api/index.html#confirm_rejection_route_api_resumes__resume_id__confirm_rejection_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/override-rejection` | [撤销自动淘汰结论](external-api/index.html#override_rejection_route_api_resumes__resume_id__override_rejection_post) | 公司 Token |
| POST | `/api/resumes/{resume_id}/transfer` | [简历转岗](external-api/index.html#transfer_resume_position_route_api_resumes__resume_id__transfer_post) | 公司 Token |

## 面试与录音

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/interviews/my-pending-review-count` | [查询待人工面试评审数量](external-api/index.html#get_my_pending_human_review_count_route_api_interviews_my_pending_review_count_get) | 公司 Token |
| POST | `/api/interviews/{interview_id}/panel-score` | [提交面试官评分](external-api/index.html#submit_panel_score_route_api_interviews__interview_id__panel_score_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/aggregate` | [汇总面试评分](external-api/index.html#aggregate_scores_route_api_interviews__interview_id__aggregate_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/confirm` | [确认面试结果](external-api/index.html#confirm_interview_result_route_api_interviews__interview_id__confirm_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/cancel` | [取消面试](external-api/index.html#cancel_interview_route_api_interviews__interview_id__cancel_post) | 公司 Token |
| GET | `/api/interviews/{interview_id}/submission-status` | [查询面试评分提交状态](external-api/index.html#get_submission_status_route_api_interviews__interview_id__submission_status_get) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/reserve` | [预约录音会话](external-api/index.html#reserve_recording_route_api_interviews__interview_id__recording_reserve_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/confirm` | [确认开始录音](external-api/index.html#confirm_recording_route_api_interviews__interview_id__recording_confirm_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/heartbeat` | [更新录音会话心跳](external-api/index.html#heartbeat_recording_route_api_interviews__interview_id__recording_heartbeat_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/realtime-session` | [创建实时转写连接凭证](external-api/index.html#create_realtime_session_route_api_interviews__interview_id__recording_realtime_session_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/realtime-transcript` | [保存实时转写片段](external-api/index.html#persist_realtime_transcript_route_api_interviews__interview_id__recording_realtime_transcript_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/chunks/{chunk_index}` | [上传录音分片](external-api/index.html#upload_recording_chunk_route_api_interviews__interview_id__recording_chunks__chunk_index__post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/end` | [结束面试](external-api/index.html#end_interview_route_api_interviews__interview_id__end_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/force-end` | [强制结束面试](external-api/index.html#force_end_interview_route_api_interviews__interview_id__force_end_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/recording/seal` | [封存录音并进入分析](external-api/index.html#seal_recording_route_api_interviews__interview_id__recording_seal_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/analysis/retry` | [重试面试分析](external-api/index.html#retry_analysis_route_api_interviews__interview_id__analysis_retry_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/transcript/import/preview` | [预览转写文件导入](external-api/index.html#preview_transcript_import_route_api_interviews__interview_id__transcript_import_preview_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/transcript/import` | [导入转写文件](external-api/index.html#import_transcript_route_api_interviews__interview_id__transcript_import_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/transcript/corrections` | [修正转写文本](external-api/index.html#correct_transcript_route_api_interviews__interview_id__transcript_corrections_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/transcript/speaker-labels` | [标记转写说话人](external-api/index.html#label_transcript_speakers_route_api_interviews__interview_id__transcript_speaker_labels_post) | 公司 Token |
| GET | `/api/interviews/{interview_id}/notes` | [查询面试笔记](external-api/index.html#interview_notes_route_api_interviews__interview_id__notes_get) | 公司 Token |
| PUT | `/api/interviews/{interview_id}/notes` | [保存面试笔记](external-api/index.html#save_interview_notes_route_api_interviews__interview_id__notes_put) | 公司 Token |
| POST | `/api/interviews/{interview_id}/notes/supplements` | [补充面试笔记](external-api/index.html#add_note_supplement_route_api_interviews__interview_id__notes_supplements_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/human-review` | [提交人工面试评审](external-api/index.html#submit_human_review_route_api_interviews__interview_id__human_review_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/final-decision` | [提交面试最终决策](external-api/index.html#final_decision_route_api_interviews__interview_id__final_decision_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/final-decision/correct` | [修正面试最终决策](external-api/index.html#correct_final_decision_route_api_interviews__interview_id__final_decision_correct_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/cancel-notification` | [重发面试取消通知](external-api/index.html#retry_cancel_notification_route_api_interviews__interview_id__cancel_notification_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/reviewers/replace` | [替换面试评审人](external-api/index.html#replace_reviewer_route_api_interviews__interview_id__reviewers_replace_post) | 公司 Token |
| PUT | `/api/interviews/{interview_id}/reviewers` | [更新面试评审人](external-api/index.html#update_reviewers_route_api_interviews__interview_id__reviewers_put) | 公司 Token |
| POST | `/api/interviews/{interview_id}/review-reminders` | [发送面试评审提醒](external-api/index.html#send_review_reminders_route_api_interviews__interview_id__review_reminders_post) | 公司 Token |
| GET | `/api/interviews/{interview_id}/export` | [导出面试结果](external-api/index.html#export_interview_route_api_interviews__interview_id__export_get) | 公司 Token |
| PUT | `/api/interviews/{interview_id}/questions` | [更新面试题目](external-api/index.html#update_questions_route_api_interviews__interview_id__questions_put) | 公司 Token |
| POST | `/api/interviews` | [安排面试](external-api/index.html#create_interview_route_api_interviews_post) | 公司 Token |
| GET | `/api/interviews` | [查询面试列表](external-api/index.html#get_interviews_route_api_interviews_get) | 公司 Token |
| GET | `/api/interviews/filter-options/interviewers` | [查询可见面试官选项](external-api/index.html#get_visible_interviewer_options_route_api_interviews_filter_options_interviewers_get) | 公司 Token |
| POST | `/api/interviews/email-preview` | [预览面试邀请邮件](external-api/index.html#preview_email_before_create_api_interviews_email_preview_post) | 公司 Token |
| GET | `/api/interviews/{interview_id}` | [查询面试详情](external-api/index.html#get_interview_route_api_interviews__interview_id__get) | 公司 Token |
| PUT | `/api/interviews/{interview_id}` | [更新面试](external-api/index.html#update_interview_route_api_interviews__interview_id__put) | 公司 Token |
| DELETE | `/api/interviews/{interview_id}` | [删除面试](external-api/index.html#delete_interview_route_api_interviews__interview_id__delete) | 公司 Token |
| POST | `/api/interviews/{interview_id}/start` | [开始面试](external-api/index.html#start_interview_route_api_interviews__interview_id__start_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/schedule-email-preview` | [预览面试改期通知](external-api/index.html#preview_schedule_update_email_api_interviews__interview_id__schedule_email_preview_post) | 公司 Token |
| PUT | `/api/interviews/{interview_id}/schedule` | [修改面试排期](external-api/index.html#update_interview_schedule_route_api_interviews__interview_id__schedule_put) | 公司 Token |
| POST | `/api/interviews/{interview_id}/schedule-notifications` | [发送面试排期通知](external-api/index.html#send_interview_schedule_notifications_api_interviews__interview_id__schedule_notifications_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/score` | [提交面试评分](external-api/index.html#submit_score_route_api_interviews__interview_id__score_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/audio/{question_index}` | [上传单题录音](external-api/index.html#upload_audio_route_api_interviews__interview_id__audio__question_index__post) | 公司 Token |
| GET | `/api/interviews/{interview_id}/email-preview` | [查询面试邮件预览](external-api/index.html#get_email_preview_api_interviews__interview_id__email_preview_get) | 公司 Token |
| POST | `/api/interviews/{interview_id}/send-email` | [发送面试邀请邮件](external-api/index.html#send_interview_email_api_interviews__interview_id__send_email_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/full-audio` | [上传完整面试录音](external-api/index.html#upload_full_interview_audio_api_interviews__interview_id__full_audio_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/direct-evaluation` | [提交直接评价](external-api/index.html#submit_direct_evaluation_api_interviews__interview_id__direct_evaluation_post) | 公司 Token |
| POST | `/api/interviews/{interview_id}/direct-evaluation-with-audio` | [上传录音并提交直接评价](external-api/index.html#submit_direct_evaluation_with_audio_api_interviews__interview_id__direct_evaluation_with_audio_post) | 公司 Token |

## 招聘统计

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/dashboard/interviewer` | [查询面试官工作台](external-api/index.html#read_interviewer_dashboard_api_dashboard_interviewer_get) | 公司 Token |
| GET | `/api/dashboard/stats` | [查询招聘统计](external-api/index.html#read_dashboard_stats_api_dashboard_stats_get) | 公司 Token |
| GET | `/api/dashboard/overview` | [查询招聘概览](external-api/index.html#read_overview_api_dashboard_overview_get) | 公司 Token |
| GET | `/api/dashboard/funnel` | [查询招聘漏斗](external-api/index.html#read_funnel_api_dashboard_funnel_get) | 公司 Token |
| GET | `/api/dashboard/positions` | [查询岗位分析](external-api/index.html#read_position_analytics_api_dashboard_positions_get) | 公司 Token |
| GET | `/api/dashboard/interviewers` | [查询面试官分析](external-api/index.html#read_interviewer_analytics_api_dashboard_interviewers_get) | 公司 Token |
| GET | `/api/dashboard/timeline` | [查询时间线分析](external-api/index.html#read_timeline_analytics_api_dashboard_timeline_get) | 公司 Token |

## 笔试管理

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| POST | `/api/coding-tests` | [创建笔试](external-api/index.html#create_coding_test_route_api_coding_tests_post) | 公司 Token |
| GET | `/api/coding-tests` | [查询笔试列表](external-api/index.html#list_coding_tests_route_api_coding_tests_get) | 公司 Token |
| POST | `/api/coding-tests/import/leetcode` | [导入算法题](external-api/index.html#import_leetcode_route_api_coding_tests_import_leetcode_post) | 公司 Token |
| POST | `/api/coding-tests/generate-questions` | [生成笔试题目](external-api/index.html#generate_questions_route_api_coding_tests_generate_questions_post) | 公司 Token |
| POST | `/api/coding-tests/{coding_test_id}/generate-questions` | [为指定笔试生成题目](external-api/index.html#generate_questions_for_test_route_api_coding_tests__coding_test_id__generate_questions_post) | 公司 Token |
| GET | `/api/coding-tests/{coding_test_id}` | [查询笔试详情](external-api/index.html#get_coding_test_route_api_coding_tests__coding_test_id__get) | 公司 Token |
| PUT | `/api/coding-tests/{coding_test_id}` | [更新笔试](external-api/index.html#update_coding_test_route_api_coding_tests__coding_test_id__put) | 公司 Token |
| DELETE | `/api/coding-tests/{coding_test_id}` | [删除笔试](external-api/index.html#delete_coding_test_route_api_coding_tests__coding_test_id__delete) | 公司 Token |
| POST | `/api/coding-tests/{coding_test_id}/publish` | [发布笔试](external-api/index.html#publish_coding_test_route_api_coding_tests__coding_test_id__publish_post) | 公司 Token |
| POST | `/api/coding-tests/{coding_test_id}/close` | [关闭笔试](external-api/index.html#close_coding_test_route_api_coding_tests__coding_test_id__close_post) | 公司 Token |
| POST | `/api/coding-tests/{coding_test_id}/public-token` | [重新生成笔试链接](external-api/index.html#reissue_coding_test_public_token_route_api_coding_tests__coding_test_id__public_token_post) | 公司 Token |
| GET | `/api/coding-tests/{coding_test_id}/submissions` | [查询笔试提交列表](external-api/index.html#list_coding_test_submissions_route_api_coding_tests__coding_test_id__submissions_get) | 公司 Token |
| GET | `/api/coding-tests/submissions/{submission_id}` | [查询笔试提交详情](external-api/index.html#get_coding_submission_route_api_coding_tests_submissions__submission_id__get) | 公司 Token |

## 候选人笔试

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/public/coding-tests/{token}` | [查询候选人笔试内容](external-api/index.html#get_public_coding_test_route_api_public_coding_tests__token__get) | 无需账号 Token |
| POST | `/api/public/coding-tests/{token}/run` | [试运行候选人代码](external-api/index.html#run_public_code_route_api_public_coding_tests__token__run_post) | 无需账号 Token |
| POST | `/api/public/coding-tests/{token}/submit` | [提交候选人代码](external-api/index.html#submit_public_code_route_api_public_coding_tests__token__submit_post) | 无需账号 Token |
| POST | `/api/public/coding-tests/{token}/submit-choice` | [提交选择题答案](external-api/index.html#submit_choice_route_api_public_coding_tests__token__submit_choice_post) | 无需账号 Token |
| POST | `/api/public/coding-tests/{token}/submit-essay` | [提交问答题答案](external-api/index.html#submit_essay_route_api_public_coding_tests__token__submit_essay_post) | 无需账号 Token |
| GET | `/api/public/coding-tests/{token}/submissions/{submission_id}` | [查询候选人提交结果](external-api/index.html#get_public_submission_route_api_public_coding_tests__token__submissions__submission_id__get) | 无需账号 Token |

## 公司配置

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/settings/system` | [查询模型配置](external-api/index.html#get_system_settings_api_settings_system_get) | 公司 Token |
| PUT | `/api/settings/system` | [更新模型配置](external-api/index.html#update_system_settings_api_settings_system_put) | 公司 Token |
| GET | `/api/settings/mail` | [查询邮件配置](external-api/index.html#get_mail_settings_api_settings_mail_get) | 公司 Token |
| PUT | `/api/settings/mail` | [更新邮件配置](external-api/index.html#update_mail_settings_api_settings_mail_put) | 公司 Token |
| POST | `/api/settings/mail/test` | [发送邮件配置测试](external-api/index.html#test_mail_settings_api_settings_mail_test_post) | 公司 Token |
| GET | `/api/settings/prompts` | [查询提示词配置](external-api/index.html#get_prompt_configs_api_settings_prompts_get) | 公司 Token |
| PUT | `/api/settings/prompts/{key}` | [更新提示词配置](external-api/index.html#update_prompt_config_api_settings_prompts__key__put) | 公司 Token |
| POST | `/api/settings/prompts/reload` | [重新加载提示词配置](external-api/index.html#reload_prompt_configs_api_settings_prompts_reload_post) | 公司 Token |
| GET | `/api/settings/prompts/variables` | [查询提示词变量](external-api/index.html#get_prompt_variables_api_settings_prompts_variables_get) | 无需账号 Token |

## Offer 管理

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| POST | `/api/offers` | [创建 Offer](external-api/index.html#create_offer_api_offers_post) | 公司 Token |
| GET | `/api/offers` | [查询 Offer 列表](external-api/index.html#list_offers_api_offers_get) | 公司 Token |
| GET | `/api/offers/stats` | [查询 Offer 统计](external-api/index.html#get_offer_stats_api_offers_stats_get) | 公司 Token |
| GET | `/api/offers/my-pending-count` | [查询待处理 Offer 数量](external-api/index.html#get_my_pending_offer_count_api_offers_my_pending_count_get) | 公司 Token |
| POST | `/api/offers/{offer_id}/confirm-onboarding` | [确认候选人入职](external-api/index.html#confirm_offer_onboarding_api_offers__offer_id__confirm_onboarding_post) | 公司 Token |
| POST | `/api/offers/{offer_id}/departure` | [登记员工离职](external-api/index.html#record_offer_departure_api_offers__offer_id__departure_post) | 公司 Token |
| GET | `/api/offers/{offer_id}` | [查询 Offer 详情](external-api/index.html#get_offer_api_offers__offer_id__get) | 公司 Token |
| PUT | `/api/offers/{offer_id}` | [更新 Offer](external-api/index.html#update_offer_api_offers__offer_id__put) | 公司 Token |
| DELETE | `/api/offers/{offer_id}` | [删除 Offer](external-api/index.html#delete_offer_api_offers__offer_id__delete) | 公司 Token |
| POST | `/api/offers/{offer_id}/mark-pending-confirmation` | [标记 Offer 待确认](external-api/index.html#mark_offer_pending_confirmation_api_offers__offer_id__mark_pending_confirmation_post) | 公司 Token |
| POST | `/api/offers/{offer_id}/decision` | [登记 Offer 结果](external-api/index.html#record_offer_decision_api_offers__offer_id__decision_post) | 公司 Token |
| GET | `/api/offers/{offer_id}/decision-audits` | [查询 Offer 决策记录](external-api/index.html#list_offer_decision_audits_api_offers__offer_id__decision_audits_get) | 公司 Token |
| POST | `/api/offers/{offer_id}/withdraw` | [撤回 Offer](external-api/index.html#withdraw_offer_api_offers__offer_id__withdraw_post) | 公司 Token |
| POST | `/api/offers/{offer_id}/reopen` | [重新打开 Offer](external-api/index.html#reopen_offer_api_offers__offer_id__reopen_post) | 公司 Token |

## Offer 模板

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| POST | `/api/offer-templates` | [创建 Offer 模板](external-api/index.html#create_template_api_offer_templates_post) | 公司 Token |
| GET | `/api/offer-templates` | [查询 Offer 模板](external-api/index.html#list_templates_api_offer_templates_get) | 公司 Token |
| GET | `/api/offer-templates/default/{position_id}` | [查询岗位默认 Offer 模板](external-api/index.html#get_default_template_api_offer_templates_default__position_id__get) | 公司 Token |
| GET | `/api/offer-templates/{template_id}` | [查询 Offer 模板详情](external-api/index.html#get_template_api_offer_templates__template_id__get) | 公司 Token |
| PUT | `/api/offer-templates/{template_id}` | [更新 Offer 模板](external-api/index.html#update_template_api_offer_templates__template_id__put) | 公司 Token |
| DELETE | `/api/offer-templates/{template_id}` | [删除 Offer 模板](external-api/index.html#delete_template_api_offer_templates__template_id__delete) | 公司 Token |

## 评审链接

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/public/review/{token}/resume-file` | [下载评审简历文件](external-api/index.html#get_resume_file_for_review_api_public_review__token__resume_file_get) | 公司 Token |
| GET | `/api/public/review/{token}` | [查询评审链接内容](external-api/index.html#get_resume_for_review_api_public_review__token__get) | 公司 Token |
| POST | `/api/public/review/{token}/submit` | [通过链接提交部门评审](external-api/index.html#submit_review_api_public_review__token__submit_post) | 公司 Token |

## 工作流

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/workflows` | [查询工作流](external-api/index.html#list_workflows_api_workflows_get) | 公司 Token |
| POST | `/api/workflows` | [创建工作流](external-api/index.html#create_workflow_api_workflows_post) | 公司 Token |
| GET | `/api/workflows/{workflow_id}` | [查询工作流详情](external-api/index.html#get_workflow_api_workflows__workflow_id__get) | 公司 Token |
| PUT | `/api/workflows/{workflow_id}` | [更新工作流](external-api/index.html#update_workflow_api_workflows__workflow_id__put) | 公司 Token |
| DELETE | `/api/workflows/{workflow_id}` | [删除工作流](external-api/index.html#delete_workflow_api_workflows__workflow_id__delete) | 公司 Token |
| POST | `/api/workflows/{workflow_id}/publish` | [发布工作流](external-api/index.html#publish_workflow_api_workflows__workflow_id__publish_post) | 公司 Token |
| POST | `/api/workflows/{workflow_id}/execute` | [执行工作流](external-api/index.html#execute_workflow_api_workflows__workflow_id__execute_post) | 公司 Token |
| GET | `/api/workflows/{workflow_id}/executions` | [查询工作流执行记录](external-api/index.html#list_executions_api_workflows__workflow_id__executions_get) | 公司 Token |
| GET | `/api/workflows/executions/{execution_id}` | [查询工作流执行详情](external-api/index.html#get_execution_api_workflows_executions__execution_id__get) | 公司 Token |

## 文件管理

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/files/{file_id}` | [下载文件](external-api/index.html#download_file_api_files__file_id__get) | 公司 Token |
| POST | `/api/files/{file_id}/public-token` | [创建限时文件链接](external-api/index.html#create_public_file_token_api_files__file_id__public_token_post) | 公司 Token |

## 临时文件下载

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/public/files/{token}` | [通过限时链接下载文件](external-api/index.html#download_public_file_api_public_files__token__get) | 无需账号 Token |

## 招聘绩效

| 方法 | 路径 | 用途 | 认证 |
| --- | --- | --- | --- |
| GET | `/api/recruitment-performance/periods` | [查询绩效周期](external-api/index.html#periods_api_recruitment_performance_periods_get) | 公司 Token |
| GET | `/api/recruitment-performance/overview` | [查询公司绩效概览](external-api/index.html#overview_api_recruitment_performance_overview_get) | 公司 Token |
| GET | `/api/recruitment-performance/me` | [查询我的绩效](external-api/index.html#my_performance_api_recruitment_performance_me_get) | 公司 Token |
| GET | `/api/recruitment-performance/leaderboard` | [查询绩效排行榜](external-api/index.html#leaderboard_api_recruitment_performance_leaderboard_get) | 公司 Token |
| GET | `/api/recruitment-performance/people/{user_id}` | [查询人员绩效详情](external-api/index.html#person_detail_api_recruitment_performance_people__user_id__get) | 公司 Token |
| GET | `/api/recruitment-performance/config` | [查询绩效配置](external-api/index.html#read_config_api_recruitment_performance_config_get) | 公司 Token |
| PUT | `/api/recruitment-performance/config` | [更新绩效配置](external-api/index.html#write_config_api_recruitment_performance_config_put) | 公司 Token |
| POST | `/api/recruitment-performance/settlements/{period}` | [结算绩效](external-api/index.html#settle_api_recruitment_performance_settlements__period__post) | 公司 Token |
| POST | `/api/recruitment-performance/slots/{slot_id}/pause-requests` | [申请暂停招聘名额](external-api/index.html#request_pause_api_recruitment_performance_slots__slot_id__pause_requests_post) | 公司 Token |
| GET | `/api/recruitment-performance/pause-requests` | [查询暂停名额申请](external-api/index.html#list_pause_requests_api_recruitment_performance_pause_requests_get) | 公司 Token |
| POST | `/api/recruitment-performance/pause-requests/{pause_id}/decision` | [审批暂停名额申请](external-api/index.html#decide_pause_api_recruitment_performance_pause_requests__pause_id__decision_post) | 公司 Token |
