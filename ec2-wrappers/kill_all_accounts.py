import subaccounts

iam_root = subaccounts.get_root_IAM_connection()

maybe_yes = raw_input("Delete all identities on account? Are you sure? (yes/NO) ");

if maybe_yes != "yes":
    print "Not proceeding"
    sys.exit(1)

subaccounts.init_db()
for user in iam_root.get_all_users()['list_users_response']['list_users_result']['users']:
    print "Deleting user ", user
    subaccounts.delete_user(user['user_name'])

