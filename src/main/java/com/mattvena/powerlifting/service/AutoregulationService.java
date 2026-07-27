package com.mattvena.powerlifting.service;

import com.mattvena.powerlifting.model.OneRmSetting;
import com.mattvena.powerlifting.model.WorkoutLog;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class AutoregulationService {

    public static class EvaluationResult {
        private final String status;
        private final String feedback;
        private final boolean updated;

        public EvaluationResult(String status, String feedback, boolean updated) {
            this.status = status;
            this.feedback = feedback;
            this.updated = updated;
        }

        public String getStatus() {
            return status;
        }

        public String getFeedback() {
            return feedback;
        }

        public boolean isUpdated() {
            return updated;
        }
    }

    public EvaluationResult evaluateWorkout(List<WorkoutLog> logs, OneRmSetting current1Rms) {
        if (logs == null || logs.isEmpty()) {
            return new EvaluationResult("SUCCESS", "수행할 운동 기록이 없습니다.", false);
        }

        // Extract day number
        String dayName = logs.get(0).getDay();
        int dayNum = 1;
        if (dayName != null) {
            if (dayName.contains("Day 1")) dayNum = 1;
            else if (dayName.contains("Day 2")) dayNum = 2;
            else if (dayName.contains("Day 3")) dayNum = 3;
            else if (dayName.contains("Day 4")) dayNum = 4;
            else if (dayName.contains("Day 5")) dayNum = 5;
        }

        boolean fatigueActiveBefore = false;
        if (dayNum == 1) fatigueActiveBefore = current1Rms.isFatigueDay1();
        else if (dayNum == 2) fatigueActiveBefore = current1Rms.isFatigueDay2();
        else if (dayNum == 3) fatigueActiveBefore = current1Rms.isFatigueDay3();
        else if (dayNum == 4) fatigueActiveBefore = current1Rms.isFatigueDay4();
        else if (dayNum == 5) fatigueActiveBefore = current1Rms.isFatigueDay5();

        boolean hasFailure = false;
        double totalRpe = 0.0;
        int rpeCount = 0;

        for (WorkoutLog log : logs) {
            if (log.getReps() < log.getTargetReps()) {
                hasFailure = true;
            }
            if (log.getRpe() > 0) {
                totalRpe += log.getRpe();
                rpeCount++;
            }
        }

        double avgRpe = rpeCount > 0 ? (totalRpe / rpeCount) : 0.0;

        // 1. Fatigue Condition: Failure + Avg RPE >= 9.0
        if (hasFailure && avgRpe >= 9.0) {
            if (dayNum == 1) current1Rms.setFatigueDay1(true);
            else if (dayNum == 2) current1Rms.setFatigueDay2(true);
            else if (dayNum == 3) current1Rms.setFatigueDay3(true);
            else if (dayNum == 4) current1Rms.setFatigueDay4(true);
            else if (dayNum == 5) current1Rms.setFatigueDay5(true);

            String msg = String.format("🚨 [신경계 피로 감지] 평균 RPE가 %.1f로 매우 높고, 목표 횟수를 달성하지 못한 세트가 존재합니다. " +
                    "과도한 피로가 누적된 상태이므로, 다음 주기 해당 부위 훈련 시 타겟 무게를 5%% 하향 조정하거나 " +
                    "세트당 목표 횟수를 1~2회 낮춘 디로드(Deload) 훈련을 적극 제안합니다.", avgRpe);
            return new EvaluationResult("FAIL", msg, true);
        }

        // 2. Failed but low RPE (normal failure)
        if (hasFailure) {
            boolean updated = false;
            if (fatigueActiveBefore) {
                if (dayNum == 1) current1Rms.setFatigueDay1(false);
                else if (dayNum == 2) current1Rms.setFatigueDay2(false);
                else if (dayNum == 3) current1Rms.setFatigueDay3(false);
                else if (dayNum == 4) current1Rms.setFatigueDay4(false);
                else if (dayNum == 5) current1Rms.setFatigueDay5(false);
                updated = true;
            }

            String msg = String.format("⚠️ [수행 실패] 일부 세트에서 목표 횟수를 채우지 못했습니다. (평균 RPE: %.1f) " +
                    "1RM은 유지되며, 다음 주기에는 동일 무게로 재도전하는 것을 추천합니다.%s", 
                    avgRpe, fatigueActiveBefore ? " (기존 신경계 피로 상태는 해제되었습니다.)" : "");
            return new EvaluationResult("FAIL", msg, updated);
        }

        // 3. Success Case (All sets achieved)
        boolean updated = false;
        if (fatigueActiveBefore) {
            if (dayNum == 1) current1Rms.setFatigueDay1(false);
            else if (dayNum == 2) current1Rms.setFatigueDay2(false);
            else if (dayNum == 3) current1Rms.setFatigueDay3(false);
            else if (dayNum == 4) current1Rms.setFatigueDay4(false);
            else if (dayNum == 5) current1Rms.setFatigueDay5(false);
            updated = true;

            String msg = "🎉 [디로드 성공] 디로드 세션을 성공적으로 완료하여 신경계 피로가 해소되었습니다! 다음 주기에는 정상 무게로 복귀합니다.";
            return new EvaluationResult("SUCCESS", msg, updated);
        }

        // Standard Success -> increase 1RM
        boolean squatUpdated = false;
        boolean benchUpdated = false;
        boolean deadliftUpdated = false;
        boolean ohpUpdated = false;

        for (WorkoutLog log : logs) {
            String ex = log.getExercise().toLowerCase();
            if (ex.contains("스쿼트") || ex.contains("squat")) {
                if (!squatUpdated) {
                    current1Rms.setSquat(current1Rms.getSquat() + 2.5);
                    squatUpdated = true;
                }
            } else if (ex.contains("벤치프레스") || ex.contains("bench")) {
                if (!benchUpdated) {
                    current1Rms.setBench(current1Rms.getBench() + 2.5);
                    benchUpdated = true;
                }
            } else if (ex.contains("데드리프트") || ex.contains("deadlift")) {
                if (!deadliftUpdated) {
                    current1Rms.setDeadlift(current1Rms.getDeadlift() + 2.5);
                    deadliftUpdated = true;
                }
            } else if (ex.contains("오버헤드 프레스") || ex.contains("ohp")) {
                if (!ohpUpdated) {
                    current1Rms.setOhp(current1Rms.getOhp() + 2.5);
                    ohpUpdated = true;
                }
            }
        }

        StringBuilder sb = new StringBuilder("🎉 [수행 성공] 오늘의 목표를 완벽하게 달성하셨습니다! ");
        if (squatUpdated || benchUpdated || deadliftUpdated || ohpUpdated) {
            sb.append("핵심 종목의 1RM이 +2.5kg 자동 상향 조정되었습니다: (");
            if (squatUpdated) sb.append("스쿼트: ").append(current1Rms.getSquat()).append("kg ");
            if (benchUpdated) sb.append("벤치프레스: ").append(current1Rms.getBench()).append("kg ");
            if (deadliftUpdated) sb.append("데드리프트: ").append(current1Rms.getDeadlift()).append("kg ");
            if (ohpUpdated) sb.append("OHP: ").append(current1Rms.getOhp()).append("kg ");
            sb.append(")");
            updated = true;
        } else {
            sb.append("보조 운동 세션이 성공적으로 완료되었습니다.");
        }

        return new EvaluationResult("SUCCESS", sb.toString(), updated);
    }
}
