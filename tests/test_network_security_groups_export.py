from scripts.network import network_security_groups_export as nsg_export


def test_collect_nsg_workbook_builds_summary_and_rule_sheets(monkeypatch):
    def fake_query(subscription_id, query):
        assert subscription_id == "sub-123"
        if query == nsg_export.NSG_SUMMARY_QUERY:
            return [
                {
                    "name": "nsg-prod",
                    "resourceGroup": "rg-network",
                    "location": "eastus",
                    "customRuleCount": 1,
                    "defaultRuleCount": 3,
                    "associatedSubnetCount": 2,
                    "associatedNicCount": 1,
                    "flowLogCount": 0,
                    "provisioningState": "Succeeded",
                    "id": "/subscriptions/sub-123/resourceGroups/rg-network/providers/Microsoft.Network/networkSecurityGroups/nsg-prod",
                    "tags": '{"env":"prod"}',
                }
            ]
        if query == nsg_export.NSG_RULES_QUERY:
            return [
                {
                    "subscriptionId": "sub-123",
                    "resourceGroup": "rg-network",
                    "nsgName": "nsg-prod",
                    "location": "eastus",
                    "ruleType": "Custom",
                    "ruleName": "AllowHttps",
                    "priority": 100,
                    "direction": "Inbound",
                    "access": "Allow",
                    "protocol": "Tcp",
                    "sourceAddressPrefix": "Internet",
                    "destinationPortRange": "443",
                    "id": "/rules/AllowHttps",
                }
            ]
        raise AssertionError("unexpected query")

    monkeypatch.setattr(nsg_export, "_query_resource_graph", fake_query)

    sheets, nsg_count, error_count = nsg_export.collect_nsg_workbook("sub-123")

    assert list(sheets) == ["Summary", "Network Security Groups", "NSG Rules"]
    assert nsg_count == 1
    assert error_count == 0
    assert sheets["Summary"]["Status"].tolist() == ["OK", "OK"]
    assert sheets["Network Security Groups"].iloc[0]["Name"] == "nsg-prod"
    assert sheets["Network Security Groups"].columns[-1] == "Tags"
    assert sheets["NSG Rules"].iloc[0]["Rule Name"] == "AllowHttps"
