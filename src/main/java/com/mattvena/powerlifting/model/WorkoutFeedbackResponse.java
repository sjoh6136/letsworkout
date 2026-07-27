package com.mattvena.powerlifting.model;

import java.util.List;
import java.util.Map;

public class WorkoutFeedbackResponse {
    private String status; // SUCCESS or FAIL
    private String feedback; // AI coaching message
    private boolean sheetsConnected; // true if connected to google sheets
    private double totalVolume;
    private int completedSets;
    private int totalSets;
    private List<String> progressReport; // list of overload progress reports
    private Map<String, Integer> weeklyMuscleSets; // cumulative sets per target muscle group for current week
    private String deloadAlert; // "session" or "weekly" or null

    public WorkoutFeedbackResponse() {}

    public WorkoutFeedbackResponse(String status, String feedback, boolean sheetsConnected, 
                                   double totalVolume, int completedSets, int totalSets, 
                                   List<String> progressReport, Map<String, Integer> weeklyMuscleSets, 
                                   String deloadAlert) {
        this.status = status;
        this.feedback = feedback;
        this.sheetsConnected = sheetsConnected;
        this.totalVolume = totalVolume;
        this.completedSets = completedSets;
        this.totalSets = totalSets;
        this.progressReport = progressReport;
        this.weeklyMuscleSets = weeklyMuscleSets;
        this.deloadAlert = deloadAlert;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getFeedback() {
        return feedback;
    }

    public void setFeedback(String feedback) {
        this.feedback = feedback;
    }

    public boolean isSheetsConnected() {
        return sheetsConnected;
    }

    public void setSheetsConnected(boolean sheetsConnected) {
        this.sheetsConnected = sheetsConnected;
    }

    public double getTotalVolume() {
        return totalVolume;
    }

    public void setTotalVolume(double totalVolume) {
        this.totalVolume = totalVolume;
    }

    public int getCompletedSets() {
        return completedSets;
    }

    public void setCompletedSets(int completedSets) {
        this.completedSets = completedSets;
    }

    public int getTotalSets() {
        return totalSets;
    }

    public void setTotalSets(int totalSets) {
        this.totalSets = totalSets;
    }

    public List<String> getProgressReport() {
        return progressReport;
    }

    public void setProgressReport(List<String> progressReport) {
        this.progressReport = progressReport;
    }

    public Map<String, Integer> getWeeklyMuscleSets() {
        return weeklyMuscleSets;
    }

    public void setWeeklyMuscleSets(Map<String, Integer> weeklyMuscleSets) {
        this.weeklyMuscleSets = weeklyMuscleSets;
    }

    public String getDeloadAlert() {
        return deloadAlert;
    }

    public void setDeloadAlert(String deloadAlert) {
        this.deloadAlert = deloadAlert;
    }
}
