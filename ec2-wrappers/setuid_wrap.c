#define _POSIX_C_SOURCE 200809L
#define _GNU_SOURCE

#include <string.h>
#include <unistd.h>
#include <stdio.h>

const char *environment[] = {
    "REAL_USERNAME=unset",
    "PATH=/bin:/usr/bin",
    NULL
};


int main(int argc, char **argv) {
    char real_username[128] = "REAL_USERNAME=";
    struct passwd *pw = getpwuid(getuid());
    if (!pw || strlen(pw->pw_name) > 20) {
        fprintf(stderr, "UID not found or name too long\n");
        return EXIT_FAILURE;
    }
    chdir("/");
    strcat(real_username, pw->pw_name);
    environment[0] = real_username;
    execve(REAL_EXECUTABLE, argv, environment);
    perror("execve");
    return EXIT_FAILURE;
}
