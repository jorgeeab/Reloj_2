import requests
import time
import json

BASE_URL = "http://localhost:5010"

def test_scheduling():
    print("--- Verifying Scheduling API ---")
    
    # 1. List existing schedules (should be empty initially)
    try:
        resp = requests.get(f"{BASE_URL}/api/schedules/list")
        if resp.status_code != 200:
            print(f"FAIL: List schedules failed: {resp.text}")
            return
        print(f"Initial schedules: {len(resp.json()['schedules'])}")
    except Exception as e:
        print(f"FAIL: Could not connect to {BASE_URL}: {e}")
        return

    # 2. Create a new interval schedule
    payload = {
        "name": "Test Interval Task",
        "protocol_name": "bombeo_simple",
        "schedule_type": "interval",
        "interval_seconds": 60,
        "duration_seconds": 5,
        "params": {"volume_ml": 50, "speed": 200}
    }
    
    try:
        resp = requests.post(f"{BASE_URL}/api/schedules/create", json=payload)
        if resp.status_code != 200:
            print(f"FAIL: Create schedule failed: {resp.text}")
            return
        
        task_id = resp.json().get("task_id")
        print(f"Created schedule with ID: {task_id}")
    except Exception as e:
        print(f"FAIL: Create request failed: {e}")
        return

    # 3. Verify it appears in the list
    try:
        resp = requests.get(f"{BASE_URL}/api/schedules/list")
        schedules = resp.json()['schedules']
        found = next((s for s in schedules if s['task_id'] == task_id), None)
        
        if found:
            print(f"SUCCESS: Schedule found in list. Next execution: {found['next_execution']}")
        else:
            print("FAIL: Schedule not found in list after creation")
            return
    except Exception as e:
        print(f"FAIL: Verify request failed: {e}")
        return

    # 4. Delete the schedule
    try:
        resp = requests.post(f"{BASE_URL}/api/schedules/{task_id}/delete")
        if resp.status_code == 200:
            print("SUCCESS: Schedule deleted")
        else:
            print(f"FAIL: Delete failed: {resp.text}")
            return
    except Exception as e:
        print(f"FAIL: Delete request failed: {e}")
        return

    # 5. Verify it's gone
    try:
        resp = requests.get(f"{BASE_URL}/api/schedules/list")
        schedules = resp.json()['schedules']
        found = next((s for s in schedules if s['task_id'] == task_id), None)
        
        if not found:
            print("SUCCESS: Schedule successfully removed from list")
        else:
            print("FAIL: Schedule still present after deletion")
    except Exception as e:
        print(f"FAIL: Final check failed: {e}")

if __name__ == "__main__":
    # Ensure server is running before running this test
    test_scheduling()
