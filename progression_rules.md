# Progressive Overload (Double Progression)

## 개요

운동의 점진적 과부하는 **Double Progression** 방식을 사용한다.

운동의 목표는 다음 순서로 진행된다.

1. 먼저 반복 횟수(Reps)를 목표 범위의 최대값까지 증가시킨다.
2. 최대 반복 횟수에 도달하면 중량(Weight)을 증가시킨다.
3. 중량이 증가하면 반복 횟수는 목표 범위의 최소값으로 초기화된다.
4. 이 과정을 반복한다.

단, **목표 RPE를 만족한 경우에만 다음 단계로 진행한다.**

---

# 운동 정보

각 운동은 다음 정보를 가진다.

| 항목 | 예시 |
|------|------|
| Weight | 10kg |
| Rep Range | 6-8 |
| Sets | 3 |
| Target RPE | 8 |

예시

```text
Weight: 10kg
Rep Range: 6-8
Sets: 3
Target RPE: 8
```

---

# 운동 기록

운동을 완료하면 실제 수행 결과를 저장한다.

예시

```text
Weight: 10kg
Reps: 6
Sets: 3
Actual RPE: 8
```

---

# 목표 업데이트 조건

다음 운동 목표는 아래 두 조건을 **모두 만족해야만** 업데이트된다.

- 운동 목표를 모두 성공했다. (모든 세트 수행 횟수 >= 목표 횟수 && 세트 수 달성)
- Actual RPE ≤ Target RPE

즉,

```text
Success AND Actual RPE <= Target RPE
```

인 경우에만 목표를 증가시킨다.

그 외의 경우에는 다음 운동도 동일한 목표를 유지한다.

---

# 반복 횟수 증가

현재 운동

```text
10kg
6-8 reps
```

현재 목표

```text
10kg × 6
```

성공 조건을 만족하면

다음 운동은

```text
10kg × 7
```

다시 성공하면

```text
10kg × 8
```

---

# 최대 반복 도달

Rep Range의 최대값까지 성공하면

중량을 증가시키고

반복 횟수는 최소값으로 초기화한다.

예시

현재

```text
10kg × 8
```

성공

↓

다음 운동

```text
증량된 Weight × 6
```

---

# 중량 증가

중량 증가량은 운동 종류에 따라 결정된다.

## 대근육 운동

증가량

```text
+5kg
```

예시

```text
10kg × 8 성공

↓

15kg × 6

↓

15kg × 7

↓

15kg × 8

↓

20kg × 6
```

---

## 소근육 운동

증가량

```text
+2.5kg
```

예시

```text
10kg × 8 성공

↓

12.5kg × 6

↓

12.5kg × 7

↓

12.5kg × 8

↓

15kg × 6
```

---

# RPE 조건

운동은 성공했더라도

Target RPE보다 Actual RPE가 높으면

다음 운동 목표는 업데이트되지 않는다.

## 예시 1

목표

```text
10kg × 6
Target RPE = 8
```

실제 기록

```text
10kg × 6
Actual RPE = 8
```

다음 운동

```text
10kg × 7
```

---

## 예시 2

목표

```text
10kg × 6
Target RPE = 8
```

실제 기록

```text
10kg × 6
Actual RPE = 9
```

다음 운동

```text
10kg × 6
```

유지된다.

---

## 예시 3

현재 목표

```text
10kg × 8
Target RPE = 8
```

실제 기록

```text
10kg × 8
Actual RPE = 10
```

원래라면

```text
15kg × 6
```

으로 증량되어야 하지만

RPE 조건을 만족하지 못했으므로

다음 운동은

```text
10kg × 8
```

을 다시 수행한다.

---

# 실패한 경우

아래 경우는 모두 목표 업데이트를 하지 않는다.

- 목표 Reps를 달성하지 못한 경우
- 목표 Sets를 완료하지 못한 경우
- Actual RPE > Target RPE

즉,

다음 운동도 동일한 목표를 유지한다.

---

# 알고리즘

```text
운동 완료

↓

목표 성공 여부 확인

↓

Target RPE 이하인가?

↓

NO
    ↓
현재 목표 유지

YES
    ↓

현재 Reps < Rep Range 최대값 ?

        │

      YES

        │

Reps + 1

        │

      END

      NO

        │

Weight += Increment

Reps = Rep Range 최소값

        │

      END
```

---

# 의사 코드

```pseudo
if success and actualRPE <= targetRPE:

    if currentReps < repRange.max:
        currentReps += 1

    else:
        weight += increment
        currentReps = repRange.min

else:

    // 목표 유지
```

---

# 예시 시나리오 (대근육)

초기 설정

```text
Weight: 10kg
Rep Range: 6-8
Sets: 3
Target RPE: 8
Increment: +5kg
```

| 회차 | 실제 수행 | 다음 목표 |
|------|-----------|-----------|
| W1D1 | 10×6 / RPE8 | 10×7 |
| W2D1 | 10×7 / RPE9 | 10×7 |
| W3D1 | 10×7 / RPE8 | 10×8 |
| W4D1 | 10×8 / RPE10 | 10×8 |
| W5D1 | 10×8 / RPE8 | 15×6 |
| W6D1 | 15×6 / RPE8 | 15×7 |
| W7D1 | 15×7 / RPE8 | 15×8 |
| W8D1 | 15×8 / RPE8 | 20×6 |

---

# 참고

- 운동이 **대근육 운동인지 소근육 운동인지**는 별도의 정의 파일(MD 또는 설정 파일)에서 관리한다.
- Progressive Overload 알고리즘은 해당 정의 파일에서 운동 분류를 조회하여 중량 증가량(Increment)을 결정한다.
- 따라서 알고리즘은 모든 운동에 동일하게 적용되며, 운동 종류에 따라 증량 폭만 달라진다.
- 운동의 진행 상태는 **마지막 수행 기록**을 기준으로 계산하며, 주차(W1, W2 등)와는 무관하게 이어진다.
