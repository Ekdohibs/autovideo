#include <stdio.h>
#include <cassert>
#include <cmath>
#include <cstdlib>

using namespace std;

int main(int argc, char** argv) {
	int inrate = atoi(argv[1]);
	int outrate = atoi(argv[2]);
	assert (inrate % outrate == 0);
	int z = inrate / outrate;
	for (;;) {
		int s = 0;
		for (int i = 0; i < z; i++) {
			int u = getchar();
			int v = getchar();
			if (v < 0) return 0;
			int16_t t = u | (v << 8);
			s += abs<int16_t>(t);
		}
		putchar(s & 0xff);
		putchar((s >> 8) & 0xff);
		putchar((s >> 16) & 0xff);
		putchar((s >> 24) & 0xff);
	}
}
